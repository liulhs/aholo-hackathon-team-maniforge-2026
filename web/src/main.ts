/**
 * The web demo: the visitor puts an object anywhere on the mat and the learned policy picks it up.
 * Physics runs in the browser (official MuJoCo WebAssembly build, same version and compiled model
 * as training), the policy runs with onnxruntime-web, three.js draws the scene.
 */
import '@fontsource-variable/bricolage-grotesque/opsz.css';
import './styles/app.css';

import loadMujoco, { type MainModule } from '@mujoco/mujoco';
import mujocoWasmUrl from '@mujoco/mujoco/mujoco.wasm?url';

import { Attempt, DEFAULT_RULES, PAGE_LYING_ADAPTER, PAGE_RETRY_RULES, type AttemptRules } from './demo/attempt';
import { makeObserver, type Observer } from './policy/observation';
import { attemptFrame } from './demo/frame';
import { placeObject } from './demo/placement';
import { ActPolicy, fetchBytes } from './policy/actPolicy';
import { SceneView } from './render/sceneView';
import { parseManifest, type SceneManifest, type SceneObject } from './sim/manifest';
import { Simulation, type ObjectPose } from './sim/simulation';
import { bindStoryCarousels } from './story/lux3dCarousel';
import { bindVideoPlayers } from './story/videoPlayer';
import { bindGuide } from './ui/guide';
import { Shelf, type ShelfItem } from './ui/shelf';
import { StatusLine } from './ui/status';

const BACKGROUND = '#e6ebef';
const TABLE_LABEL = '拖动物体，随意摆放位置';
const FIRST_POSE: ObjectPose = { x: 0.235, y: 0.045, yaw: 0.5 };
const ROTATE_STEP = Math.PI / 4;
const KEY_STEP_M = 0.01;
const TAP_MAX_MOVE_PX = 8;
const TAP_MAX_MS = 400;
const TAP_MARGIN_M = 0.03; // taps this far outside the play area still count, then get clamped
const MAX_FRAMES_PER_TICK = 3; // fall behind real time rather than freeze on slow devices

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`page is missing #${id}`);
  return element as T;
}

function asset(path: string): string {
  return `${import.meta.env.BASE_URL}${path}`;
}

/** "lifted / trials", the one way the page writes a count. */
function ratio(lifted: number, trials: number): string {
  return `${lifted} / ${trials}`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

class Loader {
  private readonly root = byId<HTMLDivElement>('loader');
  private readonly text = byId<HTMLParagraphElement>('loader-text');
  private readonly bar = byId<HTMLDivElement>('loader-bar');
  private readonly fill = byId<HTMLSpanElement>('loader-fill');

  progress(fraction: number, text?: string): void {
    if (text) this.text.textContent = text;
    this.fill.style.setProperty('--progress', String(fraction));
    this.bar.setAttribute('aria-valuenow', String(Math.round(fraction * 100)));
  }

  done(): void {
    this.root.dataset.done = 'true';
    this.root.addEventListener('transitionend', () => (this.root.hidden = true), { once: true });
    window.setTimeout(() => (this.root.hidden = true), 600); // reduced motion: no transition fires
  }

  fail(message: string): void {
    this.text.textContent = message;
    this.bar.hidden = true;
  }
}

interface Tally {
  attempts: number;
  lifted: number;
}

class Demo {
  private sim: Simulation | null = null;
  private attempt: Attempt | null = null;
  private current: SceneObject;
  private pose: ObjectPose = FIRST_POSE;
  private generation = 0; // bumps on every scene swap, so an in-flight frame never touches a disposed scene
  private dragPointer: number | null = null; // the pointer moving the object, if any
  private tap: { x: number; y: number; t: number; pointer: number } | null = null;
  private pickSeq = 0; // the latest object pick wins; slower downloads of earlier picks are dropped
  private readonly rules: AttemptRules;
  private readonly observer: Observer;
  private readonly tally: Tally = { attempts: 0, lifted: 0 };
  private lastWall = 0;
  private lag = 0;
  private stepping = false;
  private hint: string | null = null; // shown instead of the settling text, e.g. after a nudge

  constructor(
    private readonly mj: MainModule,
    private readonly manifest: SceneManifest,
    private readonly policy: ActPolicy,
    private readonly view: SceneView,
    private readonly status: StatusLine,
    private readonly shelf: Shelf,
  ) {
    this.current = manifest.objects.find((o) => o.trained) ?? manifest.objects[0];
    this.rules = {
      ...DEFAULT_RULES,
      liftSuccessM: manifest.lift_success_m,
      holdSuccessS: manifest.hold_success_s,
      minUpright: manifest.min_upright,
      ...PAGE_RETRY_RULES,
    };
    this.observer = makeObserver(policy.info.object_position ?? 'origin', PAGE_LYING_ADAPTER);
  }

  get selected(): SceneObject {
    return this.current;
  }

  /** Download an object's scene (the browser's HTTP cache makes a second visit cheap). */
  fetchScene(object: SceneObject, onProgress?: (fraction: number) => void): Promise<Uint8Array> {
    return fetchBytes(asset(`scenes/${object.mjb}`), onProgress);
  }

  /** Swap the running scene for `object`'s, freeing the old model first (each holds ~100 MB of WASM heap). */
  install(object: SceneObject, bytes: Uint8Array): void {
    this.generation += 1;
    this.attempt = null;
    const old = this.sim;
    this.sim = null;
    old?.dispose();
    const next = Simulation.fromBinary(this.mj, bytes, this.manifest.joint_names, this.manifest.fps, object.size_m);
    this.sim = next;
    this.current = object;
    this.view.show(next);
    this.onObjectChange?.(object);
  }

  onObjectChange?: (object: SceneObject) => void;

  /** Put the object at `pose` (clamped to the mat, moved off the resting arm), arm in its start pose. */
  place(pose: ObjectPose): boolean {
    const sim = this.sim;
    if (!sim) return false;
    const placed = placeObject(sim, this.manifest, this.current, pose);
    this.pose = placed.pose;
    this.hint = placed.nudged ? '距机械臂过近，已自动外移' : null;
    this.view.sync(sim);
    return placed.nudged;
  }

  start(): void {
    if (!this.sim) return;
    if (this.hint) this.status.show('settling', this.hint);
    if (!this.current.trained) {
      this.status.show('missed', '该物体尚无训练数据，请选择其他物体');
      return;
    }
    this.policy.reset();
    this.attempt = new Attempt(this.rules, this.manifest.start_pose_rad);
    if (!this.hint) this.status.showAttempt(this.attempt.current);
  }

  placeAndStart(pose: ObjectPose): void {
    this.place(pose);
    this.start();
  }

  retry(): void {
    this.placeAndStart(this.pose);
  }

  rotate(): void {
    this.placeAndStart({ ...this.pose, yaw: this.pose.yaw + ROTATE_STEP });
  }

  async pick(name: string): Promise<void> {
    const object = this.manifest.objects.find((o) => o.name === name);
    if (!object) return;
    const seq = ++this.pickSeq;
    if (object.name === this.current.name) {
      this.shelf.select(name); // a pick back to the current object cancels a pending one
      return;
    }
    this.shelf.select(name);
    this.shelf.setBusy(true);
    this.attempt = null;
    this.status.show('loading', `正在载入${object.label}`);
    try {
      const bytes = await this.fetchScene(object);
      if (seq !== this.pickSeq) return; // a later pick took over
      this.install(object, bytes);
      this.placeAndStart(this.pose);
    } catch (error: unknown) {
      if (seq !== this.pickSeq) return;
      this.shelf.select(this.current.name);
      this.status.show('error', `${object.label}载入失败：${errorText(error)}。可再次点击该卡片重试`);
    } finally {
      if (seq === this.pickSeq) this.shelf.setBusy(false);
    }
  }

  // ---------- pointer and keyboard ----------

  bindInput(canvas: HTMLCanvasElement): void {
    // capture phase: decide before OrbitControls whether this drag moves the object or the camera
    canvas.addEventListener('pointerdown', (e) => this.onPointerDown(e, canvas), { capture: true });
    canvas.addEventListener('pointermove', (e) => this.onPointerMove(e));
    canvas.addEventListener('pointerup', (e) => this.onPointerUp(e, canvas));
    canvas.addEventListener('pointercancel', (e) => {
      if (e.pointerId === this.dragPointer) this.endDrag(canvas);
      if (e.pointerId === this.tap?.pointer) this.tap = null;
    });
    canvas.addEventListener('keydown', (e) => this.onKey(e));
  }

  private onPointerDown(e: PointerEvent, canvas: HTMLCanvasElement): void {
    if (this.dragPointer !== null) {
      e.stopImmediatePropagation(); // a second finger while moving the object: ignore it
      return;
    }
    this.tap = e.isPrimary ? { x: e.clientX, y: e.clientY, t: performance.now(), pointer: e.pointerId } : null;
    if (!e.isPrimary || !this.view.overObject(e.clientX, e.clientY)) return;
    e.stopImmediatePropagation();
    this.dragPointer = e.pointerId;
    this.attempt = null;
    canvas.dataset.dragging = 'true';
    canvas.setPointerCapture(e.pointerId);
    this.view.controls.enabled = false;
    this.status.show('placing');
  }

  private onPointerMove(e: PointerEvent): void {
    if (e.pointerId !== this.dragPointer) return;
    const point = this.view.tablePoint(e.clientX, e.clientY);
    if (point) this.place({ ...this.pose, ...point });
  }

  private onPointerUp(e: PointerEvent, canvas: HTMLCanvasElement): void {
    if (this.dragPointer !== null) {
      if (e.pointerId === this.dragPointer) this.endDrag(canvas);
      return;
    }
    const tap = this.tap;
    this.tap = null;
    if (!tap || tap.pointer !== e.pointerId) return;
    const moved = Math.hypot(e.clientX - tap.x, e.clientY - tap.y);
    if (moved > TAP_MAX_MOVE_PX || performance.now() - tap.t > TAP_MAX_MS) return;
    const point = this.view.tablePoint(e.clientX, e.clientY);
    if (point && this.nearPlayArea(point)) this.placeAndStart({ ...this.pose, ...point });
  }

  /** Release (or a cancelled pointer): the object stays where it was dropped, the arm starts over. */
  private endDrag(canvas: HTMLCanvasElement): void {
    this.dragPointer = null;
    delete canvas.dataset.dragging;
    this.view.controls.enabled = true;
    this.placeAndStart(this.pose); // resets the scene too, so a tap on a held object is a fresh attempt
  }

  private nearPlayArea(point: { x: number; y: number }): boolean {
    const [x0, x1] = this.manifest.play_area_x_m;
    const [y0, y1] = this.manifest.play_area_y_m;
    return point.x > x0 - TAP_MARGIN_M && point.x < x1 + TAP_MARGIN_M && point.y > y0 - TAP_MARGIN_M && point.y < y1 + TAP_MARGIN_M;
  }

  private onKey(e: KeyboardEvent): void {
    // arrows move the object as seen on screen: up = away from the camera, right = to the screen's right
    const [fx, fy] = this.view.groundForward();
    const steps: Record<string, [number, number]> = {
      ArrowUp: [fx, fy],
      ArrowDown: [-fx, -fy],
      ArrowRight: [fy, -fx],
      ArrowLeft: [-fy, fx],
    };
    const step = steps[e.key];
    if (step) {
      e.preventDefault();
      this.attempt = null;
      this.place({ ...this.pose, x: this.pose.x + KEY_STEP_M * step[0], y: this.pose.y + KEY_STEP_M * step[1] });
      this.status.show('placing', '按 Enter 开始抓取');
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this.placeAndStart(this.pose);
    } else if (e.key === 'r' || e.key === 'R') {
      this.rotate();
    }
  }

  // ---------- real-time loop ----------

  run(): void {
    this.lastWall = performance.now();
    const tick = (now: number): void => {
      void this.advance(now).finally(() => requestAnimationFrame(tick));
    };
    requestAnimationFrame(tick);
  }

  private async advance(now: number): Promise<void> {
    const frameS = 1 / this.manifest.fps;
    this.lag += Math.min(now - this.lastWall, 250) / 1000;
    this.lastWall = now;
    let frames = 0;
    if (!this.stepping) {
      this.stepping = true;
      try {
        while (this.lag >= frameS && frames < MAX_FRAMES_PER_TICK) {
          await this.stepFrame();
          this.lag -= frameS;
          frames += 1;
        }
      } catch (error: unknown) {
        this.attempt = null;
        this.status.show('error', `仿真出错：${errorText(error)}。请点击「重新抓取」`);
      } finally {
        this.stepping = false;
      }
      if (frames === MAX_FRAMES_PER_TICK) this.lag = 0;
    }
    if (this.sim) this.view.sync(this.sim);
    this.view.render();
  }

  private async stepFrame(): Promise<void> {
    const sim = this.sim;
    if (!sim || this.dragPointer !== null) return; // while dragging, the object hangs where the pointer is
    const generation = this.generation;
    const attempt = this.attempt;
    // scene or attempt changed while the policy ran: drop the frame
    const status = await attemptFrame(sim, this.policy, attempt, () => generation === this.generation && attempt === this.attempt, this.observer);
    if (!status || !attempt) return;
    if (status.phase === 'settling' && status.round === 1 && this.hint) this.status.show('settling', this.hint);
    else this.status.showAttempt(status);
    if (attempt.finished) this.count(status.phase === 'lifted');
  }

  private count(lifted: boolean): void {
    this.tally.attempts += 1;
    if (lifted) this.tally.lifted += 1;
    byId('tally-session-row').hidden = false;
    byId('tally-session').textContent = ratio(this.tally.lifted, this.tally.attempts);
  }
}

interface Evaluation {
  policy: string;
  setup?: string;
  lifted: number;
  trials: number;
  per_object?: Record<string, string>; // "lifted/trials"
}

/** The measured rate for the object on the table, under the overall one. */
function showObjectResult(object: SceneObject, perObject: Record<string, string>): void {
  const [lifted, trials] = (perObject[object.name] ?? '').split('/').map(Number);
  byId('tally-object-row').hidden = !(trials > 0);
  if (!(trials > 0)) return;
  byId('tally-object-name').textContent = object.label;
  byId('tally-object').textContent = ratio(lifted, trials);
}

/**
 * The success rate shown on the page: preferably measured through this page's own code and setup
 * (setup "page" in policy.json, tools/eval_browser.ts), else the ONNX model's Python evaluation.
 */
function showTestResults(policyInfo: unknown): Record<string, string> {
  const all = ((policyInfo as { evaluations?: Evaluation[] }).evaluations ?? []).filter(
    (e) => typeof e.lifted === 'number' && typeof e.trials === 'number',
  );
  const page = all.filter((e) => e.setup === 'page');
  const onnx = all.filter((e) => String(e.policy).includes('.onnx') && e.setup !== 'page');
  const evaluations = page.length ? page : onnx.length ? onnx : all;
  if (!evaluations.length) return {};
  const lifted = evaluations.reduce((sum, e) => sum + e.lifted, 0);
  const trials = evaluations.reduce((sum, e) => sum + e.trials, 0);
  const rate = Math.round((100 * lifted) / trials);
  byId('tally-rate').textContent = `${rate}%`;
  byId('tally-label').textContent = page.length ? '仿真抓取成功率（含自动重试）' : '仿真抓取成功率';
  byId('tally-overall').textContent = ratio(lifted, trials);
  byId('tally-overall-row').hidden = false;
  const where = page.length ? '采用与本页相同的设置' : '在仿真中';
  byId('story-result').textContent = `上方演示即使用该模型及上述重试机制：${where}随机摆放 ${trials} 次，成功抓起 ${lifted} 次（${rate}%）。`;
  return page.length === 1 ? (page[0].per_object ?? {}) : {};
}

/**
 * The restaurant around the table: a Gaussian-splat cut of SAGE-3D / InteriorGS scene 839920
 * (sim/sage3d_background.py). Loaded after the demo runs; on phones only when asked for.
 */
const BACKDROP_URL = asset('background/restaurant_839920.sog');

function bindBackdrop(view: SceneView): void {
  const button = byId<HTMLButtonElement>('backdrop');
  const show = (): void => {
    button.setAttribute('aria-pressed', String(view.backdropVisible));
    byId('demo').dataset.backdrop = view.backdropVisible ? 'on' : 'off';
    button.disabled = false;
    button.textContent = '餐厅背景';
  };
  const load = async (): Promise<void> => {
    button.disabled = true;
    button.textContent = '背景载入中';
    try {
      await view.loadBackdrop(BACKDROP_URL);
    } catch (error: unknown) {
      button.title = `背景载入失败：${errorText(error)}`;
    } finally {
      show();
    }
  };
  button.addEventListener('click', () => {
    if (!view.hasBackdrop) void load();
    else {
      view.setBackdrop(!view.backdropVisible);
      show();
    }
  });
  const smallOrTouch = window.matchMedia('(max-width: 720px), (pointer: coarse)').matches;
  if (!smallOrTouch) void load();
}

function shelfItems(manifest: SceneManifest): ShelfItem[] {
  const ordered = [...manifest.objects].sort((a, b) => Number(b.trained) - Number(a.trained));
  return ordered.map((o) => ({
    name: o.name,
    label: o.label,
    thumbnail: asset(`scenes/${o.thumb}`),
    available: o.trained,
    note: o.trained ? undefined : '示范采集中',
  }));
}

async function boot(): Promise<void> {
  const loader = new Loader();
  bindGuide(byId<HTMLDetailsElement>('guide'));
  bindStoryCarousels(import.meta.env.BASE_URL); // the story does not wait for the demo to load
  bindVideoPlayers();
  const canvas = byId<HTMLCanvasElement>('scene');
  const status = new StatusLine(byId('status'), byId('status-text'));
  try {
    loader.progress(0.02, '正在载入物理引擎');
    const mj = await loadMujoco({ locateFile: (file: string) => (file.endsWith('.wasm') ? mujocoWasmUrl : file) });
    loader.progress(0.15, '正在载入场景配置');
    const manifestResponse = await fetch(asset('scenes/manifest.json'));
    if (!manifestResponse.ok) throw new Error(`scenes/manifest.json: HTTP ${manifestResponse.status}`);
    const manifest = parseManifest(await manifestResponse.json());

    loader.progress(0.2, '正在载入抓取模型');
    const policy = await ActPolicy.load((f) => loader.progress(0.2 + 0.35 * f));
    const policyInfoResponse = await fetch(asset('policy/policy.json'));
    const perObject = showTestResults(policyInfoResponse.ok ? await policyInfoResponse.json() : {});

    const view = new SceneView(canvas, mj, BACKGROUND);
    view.setTableLabel(TABLE_LABEL);
    let demo: Demo | null = null;
    const shelf = new Shelf(byId<HTMLUListElement>('shelf'), (name) => void demo?.pick(name));
    demo = new Demo(mj, manifest, policy, view, status, shelf);
    shelf.render(shelfItems(manifest), demo.selected.name);

    loader.progress(0.55, `正在载入${demo.selected.label}的场景`);
    demo.onObjectChange = (object) => showObjectResult(object, perObject);
    demo.install(demo.selected, await demo.fetchScene(demo.selected, (f) => loader.progress(0.55 + 0.45 * f)));
    demo.bindInput(canvas);
    window.addEventListener('resize', () => view.resize());
    byId('retry').addEventListener('click', () => demo?.retry());
    byId('rotate').addEventListener('click', () => demo?.rotate());

    loader.done();
    demo.placeAndStart(FIRST_POSE);
    demo.run();
    bindBackdrop(view);
    if (import.meta.env.DEV) Object.assign(window, { __demo: demo, __view: view }); // for automated checks only
  } catch (error: unknown) {
    loader.fail(`载入失败：${errorText(error)}。请刷新页面重试，或使用新版 Chrome、Safari 或 Edge 浏览器。`);
    status.show('error');
  }
}

void boot();
