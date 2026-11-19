/**
 * Where an object goes when a visitor drops it: clamped to the mat, and moved out along +x when the
 * spot is under the arm's resting gripper (the manifest's padded keep-out box, then a contact
 * check). Shared by the page (src/main.ts) and the evaluation harness (tools/eval_browser.ts), so
 * the measured success rate describes exactly what visitors get.
 */
import type { SceneManifest, SceneObject } from '../sim/manifest';
import type { ObjectPose, Simulation } from '../sim/simulation';

const NUDGE_STEP_M = 0.005;
const NUDGE_MAX_M = 0.1;

export interface Placement {
  pose: ObjectPose;
  nudged: boolean;
}

/** Reset `sim` with the arm in its start pose and the object at the placement for `wanted`. */
export function placeObject(sim: Simulation, manifest: SceneManifest, object: SceneObject, wanted: ObjectPose): Placement {
  const [x0, x1] = manifest.play_area_x_m;
  const [y0, y1] = manifest.play_area_y_m;
  const clamped = { ...wanted, x: Math.min(Math.max(wanted.x, x0), x1), y: Math.min(Math.max(wanted.y, y0), y1) };
  const keepOut = object.start_pose_keepout;
  const inKeepOut = (p: ObjectPose): boolean =>
    !!keepOut && p.x >= keepOut.x[0] && p.x <= keepOut.x[1] && p.y >= keepOut.y[0] && p.y <= keepOut.y[1];
  let candidate = clamped;
  for (let dx = 0; dx <= NUDGE_MAX_M + 1e-9; dx += NUDGE_STEP_M) {
    candidate = { ...clamped, x: Math.min(clamped.x + dx, x1) };
    if (inKeepOut(candidate)) continue;
    sim.reset(manifest.start_pose_rad, candidate, manifest.spawn_drop_m);
    if (!sim.objectContacts().arm) return { pose: candidate, nudged: dx > 0 };
  }
  sim.reset(manifest.start_pose_rad, candidate, manifest.spawn_drop_m); // keep sim and pose in step
  return { pose: candidate, nudged: true };
}
