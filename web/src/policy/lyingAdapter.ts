/**
 * What the policy is told about an object that has fallen over.
 *
 * The policy was trained only on standing objects, and its position input is the object's
 * bottom-centre point (the body origin). Once an object lies on its side that point sits at one
 * end of it, 2-5 cm from its middle, and the policy closes the gripper there, on air or on the
 * object's base. While the object is tipped (upright below ENGAGE_BELOW), this adapter describes
 * it the way the policy knows objects: a standing box whose footprint centre is the object's centre
 * of mass, whose long side follows the lying object's longest horizontal axis, and whose size is the
 * lying object's actual extents (long, short, height). Variant "F" of the tipped-start experiment
 * (outputs/eval/diag/tipped-start): objects starting on their side lifted 70/160 with it, 39/160 without.
 */

const ENGAGE_BELOW = 0.8; // upright (z of the up axis) below this: describe the object as lying
const RELEASE_ABOVE = 0.9; // and back to the raw state once it stands this straight again
const RESTING_ORIGIN_Z = 0; // origin height of a standing object at rest on the table

type Vec3 = [number, number, number];

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

/** The 12-number object state (lift_scene.object_state layout) of a standing box standing in for a lying object. */
export function lyingView(state: ArrayLike<number>, com: ArrayLike<number>): Float32Array {
  const c0: Vec3 = [state[3], state[4], state[5]];
  const c1: Vec3 = [state[6], state[7], state[8]];
  const columns = [c0, c1, cross(c0, c1)]; // body axes in world coordinates
  const size = [state[9], state[10], state[11]];
  const vertical = [0, 1, 2].reduce((best, k) => (Math.abs(columns[k][2]) > Math.abs(columns[best][2]) ? k : best), 0);
  const horizontal = [0, 1, 2].filter((k) => k !== vertical);
  const long = size[horizontal[0]] >= size[horizontal[1]] ? horizontal[0] : horizontal[1];
  const short = horizontal[0] === long ? horizontal[1] : horizontal[0];
  let dx = columns[long][0];
  let dy = columns[long][1];
  const n = Math.hypot(dx, dy);
  if (n > 1e-6) {
    dx /= n;
    dy /= n;
  } else {
    dx = 1;
    dy = 0;
  }
  // standing box: x axis along the long side, y = z cross x, z up
  return Float32Array.from([com[0], com[1], RESTING_ORIGIN_Z, dx, dy, 0, -dy, dx, 0, size[long], size[short], size[vertical]]);
}

/** Switches between the raw state and lyingView with hysteresis; one per policy round. */
export class LyingAdapter {
  private lying = false;

  reset(): void {
    this.lying = false;
  }

  get engaged(): boolean {
    return this.lying;
  }

  view(state: Float32Array, com: ArrayLike<number>): Float32Array {
    const upright = state[3] * state[7] - state[4] * state[6];
    if (this.lying ? upright > RELEASE_ABOVE : upright < ENGAGE_BELOW) this.lying = !this.lying;
    return this.lying ? lyingView(state, com) : state;
  }
}
