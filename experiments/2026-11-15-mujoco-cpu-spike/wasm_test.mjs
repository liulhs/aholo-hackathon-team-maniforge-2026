// Loads the same SO-101 + Lux3D MJCF in the official MuJoCo WASM build (Node),
// benchmarks stepping, and replays the Python grasp control trajectory.
import fs from 'node:fs';
import path from 'node:path';
import loadMujoco from '@mujoco/mujoco';

const SPIKE_DIR = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const MODEL_DIR = path.join(SPIKE_DIR, 'models', 'so101');
const VFS_ROOT = '/working';
const SCENES = ['scene.xml', 'scene_lux3d_box_full.xml', 'scene_lux3d_box_small.xml', 'scene_lux3d_grasp.xml'];

function copyIntoMemfs(mujoco) {
  mujoco.FS.mkdir(VFS_ROOT);
  mujoco.FS.mkdir(`${VFS_ROOT}/assets`);
  for (const f of ['so101.xml', ...SCENES]) {
    mujoco.FS.writeFile(`${VFS_ROOT}/${f}`, fs.readFileSync(path.join(MODEL_DIR, f)));
  }
  for (const f of fs.readdirSync(path.join(MODEL_DIR, 'assets'))) {
    mujoco.FS.writeFile(`${VFS_ROOT}/assets/${f}`, fs.readFileSync(path.join(MODEL_DIR, 'assets', f)));
  }
}

function bench(mujoco, model, seconds = 2, repeats = 5) {
  const data = new mujoco.MjData(model);
  const n = Math.round(seconds / model.opt.timestep);
  let best = Infinity;
  try {
    for (let r = 0; r < repeats; r++) {
      mujoco.mj_resetData(model, data);
      const t0 = performance.now();
      for (let i = 0; i < n; i++) mujoco.mj_step(model, data);
      best = Math.min(best, performance.now() - t0);
    }
    return { n, ms: best, rtf: (seconds * 1000) / best };
  } finally {
    data.delete();
  }
}

function replayGrasp(mujoco, model) {
  const { settle_steps: settleSteps, ctrl } = JSON.parse(fs.readFileSync(path.join(SPIKE_DIR, 'grasp_ctrl.json'), 'utf8'));
  const data = new mujoco.MjData(model);
  try {
    const objZ = () => data.body('lux3d_obj').xpos[2];
    for (let i = 0; i < settleSteps; i++) mujoco.mj_step(model, data);
    const z0 = objZ();
    const t0 = performance.now();
    for (const u of ctrl) {
      data.ctrl.set(u);
      mujoco.mj_step(model, data);
    }
    return { z0, z1: objZ(), steps: ctrl.length, ms: performance.now() - t0 };
  } finally {
    data.delete();
  }
}

const tLoad = performance.now();
const mujoco = await loadMujoco();
console.log(`wasm module init ${(performance.now() - tLoad).toFixed(0)} ms`);
copyIntoMemfs(mujoco);

for (const scene of SCENES) {
  const t0 = performance.now();
  let model;
  try {
    model = mujoco.MjModel.from_xml_path(`${VFS_ROOT}/${scene}`);
  } catch (err) {
    console.log(`[${scene}] LOAD FAILED: ${err?.message ?? err}`);
    continue;
  }
  const tCompile = performance.now() - t0;
  const b = bench(mujoco, model);
  console.log(`[${scene}] compile ${tCompile.toFixed(0)} ms nq=${model.nq} nu=${model.nu} | ${b.n} steps in ${b.ms.toFixed(1)} ms -> ${b.rtf.toFixed(0)}x realtime`);
  if (scene === 'scene_lux3d_grasp.xml') {
    const g = replayGrasp(mujoco, model);
    const dz = g.z1 - g.z0;
    console.log(`[grasp replay] obj z ${g.z0.toFixed(4)} -> ${g.z1.toFixed(4)} (dz=${(dz * 100).toFixed(1)} cm) ${dz > 0.03 ? 'LIFTED' : 'NOT LIFTED'}; ${g.steps} steps in ${g.ms.toFixed(1)} ms`);
  }
  model.delete();
}
