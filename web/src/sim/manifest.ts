/**
 * What sim/build_web_assets.py writes to scenes/manifest.json: the shared scene facts and one
 * entry per object. Only the fields the page uses are typed; the file documents the rest.
 */

export interface KeepOutBox {
  x: [number, number];
  y: [number, number];
}

export interface SceneObject {
  name: string;
  label: string;
  mjb: string; // <name>.mjb, or <name>.mjb.gz (gzip, unpacked in the browser)
  mjb_bytes: number;
  thumb: string;
  size_m: [number, number, number];
  trained: boolean;
  /** Where the object would touch the arm resting in its start pose (padded); placements there are moved out. */
  start_pose_keepout?: KeepOutBox | null;
}

export interface SceneManifest {
  fps: number;
  joint_names: string[];
  play_area_x_m: [number, number];
  play_area_y_m: [number, number];
  spawn_drop_m: number;
  lift_success_m: number;
  hold_success_s: number;
  min_upright: number;
  start_pose_rad: number[];
  objects: SceneObject[];
}

function isNumberPair(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every((v) => typeof v === 'number');
}

/** Check the fields the page depends on, so a stale or broken manifest fails loudly at load. */
export function parseManifest(raw: unknown): SceneManifest {
  const m = raw as Partial<SceneManifest>;
  const problems: string[] = [];
  if (typeof m.fps !== 'number') problems.push('fps');
  if (!Array.isArray(m.joint_names) || m.joint_names.length !== 6) problems.push('joint_names');
  if (!isNumberPair(m.play_area_x_m) || !isNumberPair(m.play_area_y_m)) problems.push('play area');
  if (!Array.isArray(m.start_pose_rad) || m.start_pose_rad.length !== 6) problems.push('start_pose_rad');
  for (const key of ['spawn_drop_m', 'lift_success_m', 'hold_success_s', 'min_upright'] as const) {
    if (typeof m[key] !== 'number') problems.push(key);
  }
  if (!Array.isArray(m.objects) || m.objects.length === 0) problems.push('objects');
  m.objects?.forEach((o, i) => {
    if (!o.name || !o.mjb || !Array.isArray(o.size_m) || o.size_m.length !== 3) problems.push(`objects[${i}]`);
  });
  if (problems.length) throw new Error(`scenes/manifest.json is missing or has bad: ${problems.join(', ')}`);
  return m as SceneManifest;
}
