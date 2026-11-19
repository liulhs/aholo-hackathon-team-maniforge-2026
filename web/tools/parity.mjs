// Check that MuJoCo WASM (@mujoco/mujoco in Node) reproduces Python MuJoCo's physics, and time it.
//
// Replays recorded episodes the same way sim/replay.py replay() does: mj_setState(frame 0), then
// for every frame copy that frame's recorded ctrl, compare the state with the recorded one, and
// mj_step steps_per_frame times. Inputs come from a Python export: a compiled model (.mjb, from
// mujoco.mj_saveModel) and a JSON index next to a raw float64 file of mjSTATE_INTEGRATION rows.
//
//     cd web && npm install
//     node tools/parity.mjs <model.mjb> <states.json>
//     node tools/parity.mjs <model.mjb> <states.json> --timing-frames 2000
//     node tools/parity.mjs <model.mjb> <states.json> --vfs   # load through MjVFS.addBuffer (slow)
//
// By default the .mjb is written into Emscripten's in-memory file system (FS.writeFile) and loaded
// with an empty MjVFS, which falls back to that file system. MjVFS.addBuffer converts its input
// byte by byte (about 0.2 s per MB measured), so a 100+ MB model takes tens of seconds that way.
//
// Exit code 0 when every episode replays bitwise exactly, 1 otherwise.

import { readFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { parseArgs } from 'node:util';
import loadMujoco from '@mujoco/mujoco';

const VFS_MODEL_NAME = 'model.mjb';
const MEMFS_MODEL_PATH = '/model.mjb';
const DEFAULT_TIMING_FRAMES = 1000;
const TREND_EVERY_FRAMES = 20;
const OBJECT_JOINT = 'object'; // free joint of the lifted object (sim/lift_scene.py OBJECT_BODY)

function usage(message) {
  console.error(`${message}\nUsage: node tools/parity.mjs <model.mjb> <states.json> [--timing-frames N] [--vfs]`);
  process.exit(2);
}

function readBytes(path) {
  const buf = readFileSync(path);
  return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
}

/** Loads a compiled .mjb from bytes, as a browser page would after fetch(); see the header. */
function loadModel(mj, mjbPath, useVfs) {
  const bytes = readBytes(mjbPath);
  const vfs = new mj.MjVFS();
  try {
    if (useVfs) {
      vfs.addBuffer(VFS_MODEL_NAME, bytes);
      return mj.MjModel.from_binary_path(VFS_MODEL_NAME, vfs);
    }
    mj.FS.writeFile(MEMFS_MODEL_PATH, bytes);
    try {
      return mj.MjModel.from_binary_path(MEMFS_MODEL_PATH, vfs);
    } finally {
      mj.FS.unlink(MEMFS_MODEL_PATH);
    }
  } finally {
    vfs.delete();
  }
}

/** Reads the episode index and the float64 state rows it points at. */
function loadEpisodes(indexPath) {
  const index = JSON.parse(readFileSync(indexPath, 'utf8'));
  const raw = readFileSync(join(dirname(indexPath), index.file));
  const all = new Float64Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));
  const episodes = index.episodes.map((e) => ({
    ...e,
    states: all.subarray(e.offset_doubles, e.offset_doubles + e.frames * index.state_size),
  }));
  return { index, episodes };
}

function maxAbsDiff(a, b, start = 0, end = a.length) {
  let worst = 0;
  for (let i = start; i < end; i += 1) {
    const d = Math.abs(a[i] - b[i]);
    if (d > worst || Number.isNaN(d)) worst = d;
  }
  return worst;
}

/**
 * Re-simulates one episode. Per frame returns the max |replayed - recorded| over the whole state,
 * over qpos only, and over the object's position (the state starts with time, then qpos).
 * mj_getState must write into a DoubleBuffer (WASM memory): a plain Float64Array stays untouched.
 */
function replay(mj, model, data, recorded, states, stateSize, spec, stepsPerFrame) {
  const frames = states.length / stateSize;
  const objectPos = 1 + model.jnt(OBJECT_JOINT).qposadr;
  const current = new mj.DoubleBuffer(stateSize);
  const diff = { state: new Float64Array(frames), qpos: new Float64Array(frames), object: new Float64Array(frames) };
  const row = (t) => states.subarray(t * stateSize, (t + 1) * stateSize);
  try {
    mj.mj_setState(model, data, row(0), spec);
    for (let t = 0; t < frames; t += 1) {
      if (t > 0) {
        mj.mj_setState(model, recorded, row(t), spec);
        data.ctrl.set(recorded.ctrl); // the command the operator gave for frame t
        mj.mj_getState(model, data, current, spec);
        const view = current.GetView(); // fresh view each time: WASM memory may have grown
        diff.state[t] = maxAbsDiff(view, row(t));
        diff.qpos[t] = maxAbsDiff(view, row(t), 1, 1 + model.nq);
        diff.object[t] = maxAbsDiff(view, row(t), objectPos, objectPos + 3);
      }
      for (let s = 0; s < stepsPerFrame; s += 1) mj.mj_step(model, data);
    }
    return diff;
  } finally {
    current.delete();
  }
}

function maxOf(values) {
  return values.reduce((worst, v) => Math.max(worst, v), 0);
}

function describe(episode, diff) {
  const worst = maxOf(diff.state);
  const head = `episode ${String(episode.episode).padStart(3)}: ${String(episode.frames).padStart(4)} frames,`;
  if (worst === 0) return `${head} exact (bitwise)`;
  const trend = [];
  for (let t = TREND_EVERY_FRAMES; t < diff.qpos.length; t += TREND_EVERY_FRAMES) {
    trend.push(`${t}:${diff.qpos[t].toExponential(0)}`);
  }
  return `${head} state max ${worst.toExponential(2)} (first nonzero frame ${diff.state.findIndex((v) => v !== 0)}), `
    + `qpos max ${maxOf(diff.qpos).toExponential(2)}, object position max ${maxOf(diff.object).toExponential(2)} m`
    + `\n      qpos diff by frame ${trend.join(' ')}`;
}

function percentile(sorted, p) {
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

/** Times frames (stepsPerFrame mj_step calls) while replaying the episodes' controls in a loop. */
function timeFrames(mj, model, data, recorded, episodes, stateSize, spec, stepsPerFrame, count) {
  const times = [];
  while (times.length < count) {
    for (const { states } of episodes) {
      const frames = states.length / stateSize;
      mj.mj_setState(model, data, states.subarray(0, stateSize), spec);
      for (let t = 0; t < frames && times.length < count; t += 1) {
        mj.mj_setState(model, recorded, states.subarray(t * stateSize, (t + 1) * stateSize), spec);
        data.ctrl.set(recorded.ctrl);
        const start = performance.now();
        for (let s = 0; s < stepsPerFrame; s += 1) mj.mj_step(model, data);
        times.push(performance.now() - start);
      }
    }
  }
  const sorted = [...times].sort((a, b) => a - b);
  const mean = times.reduce((sum, v) => sum + v, 0) / times.length;
  return { mean, p50: percentile(sorted, 0.5), p95: percentile(sorted, 0.95), max: sorted.at(-1) };
}

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      'timing-frames': { type: 'string', default: String(DEFAULT_TIMING_FRAMES) },
      vfs: { type: 'boolean', default: false },
    },
  });
  if (positionals.length !== 2) usage('Need the model and the states index.');
  const [mjbPath, indexPath] = positionals;
  const timingFrames = Number.parseInt(values['timing-frames'], 10);
  if (!Number.isInteger(timingFrames) || timingFrames < 0) usage('--timing-frames must be a whole number.');

  const mj = await loadMujoco();
  const { index, episodes } = loadEpisodes(indexPath);
  const loadStart = performance.now();
  const model = loadModel(mj, mjbPath, values.vfs);
  const loadMs = performance.now() - loadStart;
  const data = new mj.MjData(model);
  const recorded = new mj.MjData(model); // unpacks each recorded state to read its ctrl
  try {
    const spec = mj.mjtState.mjSTATE_INTEGRATION.value;
    const stateSize = mj.mj_stateSize(model, spec);
    console.log(`MuJoCo WASM ${mj.mj_versionString()} (recorded with ${index.mujoco_version}); `
      + `${basename(mjbPath)} loaded via ${values.vfs ? 'MjVFS.addBuffer' : 'FS.writeFile'} in ${loadMs.toFixed(0)} ms; `
      + `timestep ${model.opt.timestep}`);
    if (spec !== index.state_spec_value || stateSize !== index.state_size) {
      throw new Error(`State layout differs: spec ${spec}/${index.state_spec_value}, size ${stateSize}/${index.state_size}`);
    }

    let mismatched = 0;
    for (const episode of episodes) {
      const diff = replay(mj, model, data, recorded, episode.states, stateSize, spec, index.steps_per_frame);
      mismatched += maxOf(diff.state) !== 0 ? 1 : 0;
      console.log(describe(episode, diff));
    }
    console.log(`${episodes.length - mismatched}/${episodes.length} episodes replay exactly`);

    if (timingFrames > 0) {
      const t = timeFrames(mj, model, data, recorded, episodes, stateSize, spec, index.steps_per_frame, timingFrames);
      console.log(`one 20 fps frame (${index.steps_per_frame} x mj_step) over ${timingFrames} frames: `
        + `mean ${t.mean.toFixed(3)} ms, p50 ${t.p50.toFixed(3)}, p95 ${t.p95.toFixed(3)}, max ${t.max.toFixed(3)}`);
    }
    return mismatched === 0 ? 0 : 1;
  } finally {
    recorded.delete();
    data.delete();
    model.delete();
  }
}

process.exitCode = await main();
