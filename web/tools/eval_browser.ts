/**
 * Let the grasp policy run through the web page's own code path, in Node, and count how often it
 * lifts the object: MuJoCo WebAssembly (@mujoco/mujoco) + onnxruntime-web (the same 'onnxruntime-web/wasm'
 * entry and .wasm the page loads) + the page's modules, imported unchanged:
 *   src/sim/simulation.ts (Simulation), src/policy/temporalEnsembler.ts (TemporalEnsembler),
 *   src/demo/attempt.ts (Attempt), src/sim/manifest.ts (parseManifest).
 * Only src/policy/actPolicy.ts is replaced (NodePolicy below): it fetches over HTTP and imports the
 * .wasm with Vite's `?url`, which Node cannot do. NodePolicy.act is its act() line for line.
 * Every frame does what the page does: policy on (jointAngles(), objectState()) -> TemporalEnsembler
 * -> Simulation.command -> Simulation.stepFrame, one policy call per 20 fps frame.
 *
 *     cd web && npx tsx tools/eval_browser.ts <mode> [options]
 *
 * Modes:
 *   ort-check --reference ref.json   onnxruntime-web outputs vs saved Python onnxruntime outputs
 *   matched   --trials trials.json   replay sim/evaluate.py trials (arm at an episode's first frame,
 *                                    10 settle frames, up to 20 s, evaluate.py's success rule;
 *                                    --fixed-start puts the arm at manifest start_pose_rad instead)
 *   page      --per-object 60        the page's setup: arm at manifest start_pose_rad, random spot and
 *                                    yaw on the mat, placed and judged as src/main.ts + attempt.ts do
 *                                    (--grace S overrides Attempt's knockedOverGraceS, to measure that rule)
 * Common options: --scenes DIR (default public/scenes), --policy DIR (default public/policy),
 *   --objects a,b (default: trained objects), --out results.json, --limit N (trials per object).
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { parseArgs } from 'node:util';

import loadMujoco, { type MainModule } from '@mujoco/mujoco';
import * as ort from 'onnxruntime-web/wasm';

import { Attempt, DEFAULT_RULES, PAGE_LYING_ADAPTER, PAGE_RETRY_RULES, type AttemptRules } from '../src/demo/attempt';
import { attemptFrame } from '../src/demo/frame';
import { makeObserver, type ObjectPosition } from '../src/policy/observation';
import { placeObject } from '../src/demo/placement';
import { TemporalEnsembler } from '../src/policy/temporalEnsembler';
import { parseManifest, type SceneManifest, type SceneObject } from '../src/sim/manifest';
import { Simulation, type ObjectPose } from '../src/sim/simulation';

const require = createRequire(import.meta.url);

// sim/evaluate.py
const SETTLE_FRAMES = 10;
const SETTLED_SHIFT_M = 0.003;
const SETTLED_UPRIGHT = 0.99;
const MAX_SECONDS = 20;
const MIN_UPRIGHT = 0.8; // build_state_dataset.MIN_UPRIGHT
// src/main.ts
const NEAR_ARM_X_M = 0.2;

// ---------------------------------------------------------------- policy (actPolicy.ts for Node)

interface PolicyInfo {
  chunk_size: number;
  fps: number;
  joint_names: string[];
  temporal_ensemble_coeff: number;
  object_position?: ObjectPosition;
}

class Timer {
  readonly samples: number[] = [];
  add(ms: number): void {
    this.samples.push(ms);
  }
}

class NodePolicy {
  readonly callMs = new Timer();

  private constructor(
    private readonly session: ort.InferenceSession,
    readonly info: PolicyInfo,
    private readonly ensembler: TemporalEnsembler,
  ) {}

  static async load(policyDir: string): Promise<NodePolicy> {
    ort.env.wasm.numThreads = 1; // as ActPolicy.load
    // the page sets wasmPaths to the bundled .wasm URL; Node's fetch cannot read file: URLs, so hand over the same bytes
    ort.env.wasm.wasmBinary = readBytes(require.resolve('onnxruntime-web/ort-wasm-simd-threaded.wasm'));
    const info = JSON.parse(readFileSync(join(policyDir, 'policy.json'), 'utf8')) as PolicyInfo;
    const weights = readBytes(join(policyDir, 'policy.onnx'));
    const session = await ort.InferenceSession.create(weights, { executionProviders: ['wasm'] });
    const actionDim = info.joint_names.length;
    return new NodePolicy(session, info, new TemporalEnsembler(info.temporal_ensemble_coeff, info.chunk_size, actionDim));
  }

  reset(): void {
    this.ensembler.reset();
  }

  /** The raw chunk, for ort-check. */
  async chunk(jointRad: ArrayLike<number>, objectState: ArrayLike<number>): Promise<Float32Array> {
    const result = await this.session.run(feeds(jointRad, objectState));
    const data = Float32Array.from(result.actions.data as Float32Array);
    for (const tensor of Object.values(result)) tensor.dispose();
    return data;
  }

  /** ActPolicy.act, plus timing of the whole call. */
  async act(jointRad: ArrayLike<number>, objectState: ArrayLike<number>): Promise<Float64Array> {
    const t0 = performance.now();
    const result = await this.session.run(feeds(jointRad, objectState));
    const chunk = result.actions;
    try {
      return this.ensembler.update(chunk.data as Float32Array);
    } finally {
      for (const tensor of Object.values(result)) tensor.dispose();
      this.callMs.add(performance.now() - t0);
    }
  }
}

function feeds(jointRad: ArrayLike<number>, objectState: ArrayLike<number>): Record<string, ort.Tensor> {
  return {
    state: new ort.Tensor('float32', Float32Array.from(jointRad), [1, jointRad.length]),
    env_state: new ort.Tensor('float32', Float32Array.from(objectState), [1, objectState.length]),
  };
}

// ---------------------------------------------------------------- helpers

function readBytes(path: string): Uint8Array {
  const raw = readFileSync(path);
  const buf = path.endsWith('.gz') ? gunzipSync(raw) : raw; // the site ships scenes gzipped
  return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
}

function percentile(values: number[], p: number): number {
  if (!values.length) return Number.NaN;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

function timing(timer: Timer): { n: number; median_ms: number; p95_ms: number; mean_ms: number } {
  const s = timer.samples;
  const mean = s.reduce((a, b) => a + b, 0) / (s.length || 1);
  return { n: s.length, median_ms: percentile(s, 0.5), p95_ms: percentile(s, 0.95), mean_ms: mean };
}

/** Deterministic uniform [0, 1) numbers (mulberry32). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function loadScene(mj: MainModule, manifest: SceneManifest, scenesDir: string, object: SceneObject): Simulation {
  const t0 = performance.now();
  const bytes = readBytes(join(scenesDir, object.mjb));
  const sim = Simulation.fromBinary(mj, bytes, manifest.joint_names, manifest.fps, object.size_m);
  console.error(`${object.name}: loaded ${(bytes.length / 1e6).toFixed(0)} MB in ${(performance.now() - t0).toFixed(0)} ms`);
  return sim;
}

/** evaluate.object_contact_bodies - {0}: the arm (anything but the world) touches the object. */
function armTouches(sim: Simulation): boolean {
  return sim.objectContacts().arm;
}

// ---------------------------------------------------------------- experiment 1: evaluate.py's trials

interface MatchedTrial {
  seed: number;
  index: number;
  object_name: string;
  x: number;
  y: number;
  yaw: number;
  start_index: number;
  success: boolean;
  seconds: number;
}

interface MatchedInput {
  starts: number[][];
  trials: MatchedTrial[];
}

/** evaluate.set_up_trial: arm at `start`, object settled at `pose`; reports whether the start was clear. */
function setUpTrial(sim: Simulation, manifest: SceneManifest, pose: ObjectPose, start: number[]): { clear: boolean; settled: boolean } {
  sim.reset(start, pose, manifest.spawn_drop_m);
  const clear = !armTouches(sim);
  for (let f = 0; f < SETTLE_FRAMES; f += 1) sim.stepFrame();
  const s = sim.objectState();
  const shift = Math.hypot(s[0] - pose.x, s[1] - pose.y);
  const settled = shift < SETTLED_SHIFT_M && sim.objectUpright() > SETTLED_UPRIGHT && !armTouches(sim);
  return { clear, settled };
}

/** evaluate.run_trial with SuccessTracker: lift >= 0.05 m for 1 s of sim time, table contact allowed. */
async function runMatched(sim: Simulation, policy: NodePolicy, manifest: SceneManifest, frameMs: Timer, stepMs: Timer) {
  const maxFrames = Math.round(MAX_SECONDS * manifest.fps);
  policy.reset();
  const observer = makeObserver(policy.info.object_position ?? 'origin', false); // evaluate.py has no lying adapter
  let liftedSince: number | null = null;
  let maxLift = 0;
  let knockedOverAt: number | null = null;
  let success = false;
  let framesRun = 0; // evaluate.py reports (frame + 1) / FPS: the time limit, or when it succeeded
  for (let frame = 0; frame < maxFrames; frame += 1) {
    framesRun = frame + 1;
    const t0 = performance.now();
    sim.command(await policy.act(sim.jointAngles(), observer.observe(sim)));
    const t1 = performance.now();
    sim.stepFrame();
    stepMs.add(performance.now() - t1);
    const lift = sim.objectLift();
    maxLift = Math.max(maxLift, lift);
    const onTable = sim.objectContacts().table;
    if (knockedOverAt === null && onTable && sim.objectUpright() < MIN_UPRIGHT) knockedOverAt = (frame + 1) / manifest.fps;
    frameMs.add(performance.now() - t0);
    if (lift < manifest.lift_success_m) {
      liftedSince = null;
      continue;
    }
    liftedSince ??= sim.time;
    if (sim.time - liftedSince >= manifest.hold_success_s) {
      success = true;
      break;
    }
  }
  return { success, seconds: framesRun / manifest.fps, max_lift_m: maxLift, knocked_over_at: knockedOverAt };
}

async function matched(mj: MainModule, manifest: SceneManifest, policy: NodePolicy, args: Args) {
  const input = JSON.parse(readFileSync(args.trials!, 'utf8')) as MatchedInput;
  const frameMs = new Timer();
  const stepMs = new Timer();
  const results = [];
  for (const object of selectedObjects(manifest, args)) {
    const trials = input.trials.filter((t) => t.object_name === object.name).slice(0, args.limit);
    if (!trials.length) continue;
    const sim = loadScene(mj, manifest, args.scenes, object);
    try {
      for (const t of trials) {
        const start = args.fixedStart ? manifest.start_pose_rad : input.starts[t.start_index];
        const setup = setUpTrial(sim, manifest, { x: t.x, y: t.y, yaw: t.yaw }, start);
        const run = await runMatched(sim, policy, manifest, frameMs, stepMs);
        results.push({ ...t, py_success: t.success, py_seconds: t.seconds, ...setup, ...run });
      }
    } finally {
      sim.dispose();
    }
    const done = results.filter((r) => r.object_name === object.name);
    const differ = done.filter((r) => r.success !== r.py_success).length;
    console.error(
      `${object.name}: web ${done.filter((r) => r.success).length}/${done.length}, python ${done.filter((r) => r.py_success).length}/${done.length}, outcome differs in ${differ}`,
    );
  }
  return { mode: 'matched', results, timing: { policy_call: timing(policy.callMs), frame: timing(frameMs), physics_step_frame: timing(stepMs) } };
}

// ---------------------------------------------------------------- experiment 2: the page's setup


/** Demo.start + Demo.stepFrame (src/demo/frame.ts, as the page runs it) until the attempt finishes. */
async function runPageAttempt(sim: Simulation, policy: NodePolicy, rules: AttemptRules, home: number[], frameMs: Timer, observer: Observer) {
  policy.reset();
  const attempt = new Attempt(rules, home);
  let lyingFrames = 0;
  let maxLift = 0;
  let knockedInRound: number[] = [];
  while (!attempt.finished) {
    const t0 = performance.now();
    const status = await attemptFrame(sim, policy, attempt, () => true, observer);
    if (observer.lyingView) lyingFrames += 1;
    frameMs.add(performance.now() - t0);
    maxLift = Math.max(maxLift, sim.objectLift());
    if (status?.phase === 'recovering' && !knockedInRound.includes(status.round)) knockedInRound = [...knockedInRound, status.round];
  }
  const status = attempt.current;
  return {
    phase: status.phase,
    miss_reason: status.missReason ?? null,
    lifted_after_s: status.liftedAfter ?? null,
    elapsed_s: status.elapsed,
    rounds: status.round,
    knocked_in_rounds: knockedInRound,
    max_lift_m: maxLift,
    lying_view_frames: lyingFrames,
  };
}

async function page(mj: MainModule, manifest: SceneManifest, policy: NodePolicy, args: Args) {
  const rules: AttemptRules = {
    ...DEFAULT_RULES,
    liftSuccessM: manifest.lift_success_m,
    holdSuccessS: manifest.hold_success_s,
    minUpright: manifest.min_upright,
    ...PAGE_RETRY_RULES,
    ...(args.grace === undefined ? {} : { knockedOverGraceS: args.grace }), // experiment only; the page uses the default
    ...(args.retries === undefined ? {} : { maxRetries: args.retries }),
    ...(args.roundSeconds === undefined ? {} : { roundSeconds: args.roundSeconds }),
    ...(args.knockedRetry === undefined ? {} : { knockedRetryS: args.knockedRetry }),
  };
  const frameMs = new Timer();
  const stepMs = new Timer();
  const results = [];
  const [x0, x1] = manifest.play_area_x_m;
  const [y0, y1] = manifest.play_area_y_m;
  for (const object of selectedObjects(manifest, args)) {
    const random = rng(args.seed); // the same spots for every object
    const poses = Array.from({ length: args.perObject }, () => ({
      x: x0 + random() * (x1 - x0),
      y: y0 + random() * (y1 - y0),
      yaw: -Math.PI + random() * 2 * Math.PI,
    })).slice(0, args.limit);
    const sim = loadScene(mj, manifest, args.scenes, object);
    try {
      for (const [index, requested] of poses.entries()) {
        const placed = placeObject(sim, manifest, object, requested);
        const armTouchingAtStart = sim.objectContacts().arm;
        const run = await runPageAttempt(sim, policy, rules, manifest.start_pose_rad, frameMs, makeObserver(policy.info.object_position ?? 'origin', args.lyingAdapter));
        results.push({
          object_name: object.name,
          index,
          requested,
          placed: placed.pose,
          nudged: placed.nudged,
          nudge_m: placed.pose.x - Math.min(Math.max(requested.x, x0), x1),
          arm_touching_at_start: armTouchingAtStart,
          near_arm: placed.pose.x < NEAR_ARM_X_M,
          ...run,
        });
      }
    } finally {
      sim.dispose();
    }
    const done = results.filter((r) => r.object_name === object.name);
    const lifted = done.filter((r) => r.phase === 'lifted').length;
    console.error(`${object.name}: page rules ${lifted}/${done.length} lifted`);
  }
  return { mode: 'page', seed: args.seed, rules, lying_adapter: args.lyingAdapter, results, timing: { policy_call: timing(policy.callMs), frame: timing(frameMs), physics_step_frame: timing(stepMs) } };
}

// ---------------------------------------------------------------- onnxruntime-web vs Python onnxruntime

async function ortCheck(policy: NodePolicy, args: Args) {
  const ref = JSON.parse(readFileSync(args.reference!, 'utf8')) as {
    onnxruntime: string;
    cases: Array<{ state: number[]; env_state: number[]; actions: number[] }>;
  };
  let worst = 0;
  let exact = 0;
  for (const c of ref.cases) {
    const out = await policy.chunk(c.state, c.env_state);
    let caseWorst = 0;
    out.forEach((v, i) => {
      caseWorst = Math.max(caseWorst, Math.abs(v - c.actions[i]));
    });
    worst = Math.max(worst, caseWorst);
    if (caseWorst === 0) exact += 1;
  }
  const calls = new Timer();
  const c = ref.cases[0];
  for (let i = 0; i < 1000; i += 1) {
    const t0 = performance.now();
    await policy.chunk(c.state, c.env_state);
    calls.add(performance.now() - t0);
  }
  const summary = { mode: 'ort-check', python_onnxruntime: ref.onnxruntime, onnxruntime_web: ort.env.versions, cases: ref.cases.length, bit_exact_cases: exact, max_abs_diff_rad: worst, call_timing_1000: timing(calls) };
  console.error(JSON.stringify(summary));
  return summary;
}

// ---------------------------------------------------------------- main

interface Args {
  mode: string;
  scenes: string;
  policy: string;
  objects?: string[];
  trials?: string;
  reference?: string;
  perObject: number;
  fixedStart: boolean;
  seed: number;
  limit?: number;
  grace?: number;
  retries?: number;
  roundSeconds?: number;
  knockedRetry?: number;
  lyingAdapter: boolean;
  out?: string;
}

function selectedObjects(manifest: SceneManifest, args: Args): SceneObject[] {
  const trained = manifest.objects.filter((o) => o.trained);
  if (!args.objects) return trained;
  return args.objects.map((name) => {
    const found = manifest.objects.find((o) => o.name === name);
    if (!found) throw new Error(`no object ${name} in the manifest`);
    return found;
  });
}

function parse(): Args {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      scenes: { type: 'string', default: 'public/scenes' },
      policy: { type: 'string', default: 'public/policy' },
      objects: { type: 'string' },
      trials: { type: 'string' },
      reference: { type: 'string' },
      'per-object': { type: 'string', default: '60' },
      'fixed-start': { type: 'boolean', default: false },
      seed: { type: 'string', default: '20261119' },
      limit: { type: 'string' },
      grace: { type: 'string' },
      retries: { type: 'string' },
      'round-seconds': { type: 'string' },
      'knocked-retry': { type: 'string' },
      'lying-adapter': { type: 'string', default: String(PAGE_LYING_ADAPTER) }, // true | false
      out: { type: 'string' },
    },
  });
  const mode = positionals[0];
  if (!['ort-check', 'matched', 'page'].includes(mode)) throw new Error('mode must be ort-check, matched or page');
  if (mode === 'matched' && !values.trials) throw new Error('matched needs --trials');
  if (mode === 'ort-check' && !values.reference) throw new Error('ort-check needs --reference');
  return {
    mode,
    scenes: values.scenes!,
    policy: values.policy!,
    objects: values.objects?.split(','),
    trials: values.trials,
    reference: values.reference,
    perObject: Number(values['per-object']),
    fixedStart: values['fixed-start']!,
    seed: Number(values.seed),
    limit: values.limit ? Number(values.limit) : undefined,
    grace: values.grace ? Number(values.grace) : undefined,
    retries: values.retries === undefined ? undefined : Number(values.retries),
    roundSeconds: values['round-seconds'] ? Number(values['round-seconds']) : undefined,
    knockedRetry: values['knocked-retry'] ? Number(values['knocked-retry']) : undefined,
    lyingAdapter: values['lying-adapter'] === 'true',
    out: values.out,
  };
}

async function main(): Promise<void> {
  const args = parse();
  const t0 = performance.now();
  const policy = await NodePolicy.load(args.policy);
  let output: unknown;
  if (args.mode === 'ort-check') {
    output = await ortCheck(policy, args);
  } else {
    const mj = await loadMujoco();
    const manifest = parseManifest(JSON.parse(readFileSync(join(args.scenes, 'manifest.json'), 'utf8')));
    output = args.mode === 'matched' ? await matched(mj, manifest, policy, args) : await page(mj, manifest, policy, args);
    console.error(JSON.stringify((output as { timing: unknown }).timing));
  }
  console.error(`done in ${((performance.now() - t0) / 1000).toFixed(0)} s`);
  if (args.out) writeFileSync(args.out, JSON.stringify(output, null, 1));
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
