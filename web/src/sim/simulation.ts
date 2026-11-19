/**
 * One lift scene in the browser's MuJoCo: the SO-101 arm, the table and one object, loaded from a
 * compiled model (sim/build_web_assets.py) so the physics is the same model Python trained and
 * evaluated on. Mirrors what sim/lift_scene.py, sim/teleop.py (SimArm) and sim/evaluate.py do.
 */
import type { MainModule, MjData, MjModel } from '@mujoco/mujoco';

export const OBJECT_BODY = 'object';
const OBJECT_JOINT = 'object';
const WORLD_BODY = 0;

export interface ObjectPose {
  x: number;
  y: number;
  yaw: number;
}

/** 3x3 rotation matrix (row-major) of a quaternion (w, x, y, z), term for term as MuJoCo's mju_quat2Mat. */
export function quatToMat(w: number, x: number, y: number, z: number): number[] {
  if (w === 1 && x === 0 && y === 0 && z === 0) return [1, 0, 0, 0, 1, 0, 0, 0, 1];
  const [ww, xx, yy, zz] = [w * w, x * x, y * y, z * z];
  const [wx, wy, wz, xy, xz, yz] = [w * x, w * y, w * z, x * y, x * z, y * z];
  return [
    ww + xx - yy - zz, 2 * (xy - wz), 2 * (xz + wy),
    2 * (xy + wz), ww - xx + yy - zz, 2 * (yz - wx),
    2 * (xz - wy), 2 * (yz + wx), ww - xx - yy + zz,
  ];
}

export class Simulation {
  readonly model: MjModel;
  readonly data: MjData;
  readonly stepsPerFrame: number;
  readonly objectSize: Float64Array;
  private readonly armQposAdr: number[];
  private readonly armActuator: number[];
  private readonly ctrlRange: Array<[number, number]>;
  private readonly objectQposAdr: number;
  private readonly objectDofAdr: number;
  readonly objectBody: number;

  constructor(
    private readonly mj: MainModule,
    model: MjModel,
    readonly jointNames: string[],
    fps: number,
    objectSize: ArrayLike<number>, // manifest size_m: lift_scene.object_size_m, copied, not recomputed
  ) {
    this.model = model;
    this.data = new mj.MjData(model);
    this.stepsPerFrame = Math.max(1, Math.round(1 / fps / model.opt.timestep));
    const id = (type: number, name: string): number => {
      const found = mj.mj_name2id(model, type, name);
      if (found < 0) throw new Error(`model has no ${name}`);
      return found;
    };
    const { mjOBJ_JOINT, mjOBJ_ACTUATOR, mjOBJ_BODY } = mj.mjtObj;
    this.armQposAdr = jointNames.map((name) => model.jnt_qposadr[id(mjOBJ_JOINT.value, name)]);
    this.armActuator = jointNames.map((name) => id(mjOBJ_ACTUATOR.value, name));
    this.ctrlRange = this.armActuator.map((a) => [model.actuator_ctrlrange[2 * a], model.actuator_ctrlrange[2 * a + 1]]);
    const objectJoint = id(mjOBJ_JOINT.value, OBJECT_JOINT);
    this.objectQposAdr = model.jnt_qposadr[objectJoint];
    this.objectDofAdr = model.jnt_dofadr[objectJoint];
    this.objectBody = id(mjOBJ_BODY.value, OBJECT_BODY);
    this.objectSize = Float64Array.from(objectSize);
  }

  static fromBinary(
    mj: MainModule,
    bytes: Uint8Array,
    jointNames: string[],
    fps: number,
    objectSize: ArrayLike<number>,
  ): Simulation {
    // Through Emscripten's file system: MjVFS.addBuffer copies byte by byte (about 30 s for 100 MB).
    const path = '/scene.mjb';
    const vfs = new mj.MjVFS();
    try {
      mj.FS.writeFile(path, bytes);
      const model = mj.MjModel.from_binary_path(path, vfs);
      return new Simulation(mj, model, jointNames, fps, objectSize);
    } finally {
      vfs.delete();
      mj.FS.unlink(path);
    }
  }

  dispose(): void {
    this.data.delete();
    this.model.delete();
  }

  get time(): number {
    return this.data.time;
  }

  jointAngles(): Float64Array {
    const qpos = this.data.qpos;
    return Float64Array.from(this.armQposAdr, (adr) => qpos[adr]);
  }

  /** Set the position targets, clipped to the actuators' range (SimArm.command). */
  command(angles: ArrayLike<number>): void {
    const ctrl = this.data.ctrl;
    this.armActuator.forEach((actuator, i) => {
      const [low, high] = this.ctrlRange[i];
      ctrl[actuator] = Math.min(Math.max(angles[i], low), high);
    });
  }

  /** Start over: arm at `angles` holding still, object at `pose` just above the table (SimArm.place, place_object). */
  reset(angles: ArrayLike<number>, pose: ObjectPose, dropM: number): void {
    this.mj.mj_resetData(this.model, this.data);
    const qpos = this.data.qpos;
    this.armQposAdr.forEach((adr, i) => {
      qpos[adr] = angles[i];
    });
    this.command(angles);
    this.placeObject(pose, dropM);
  }

  /** Put the object at `pose`, at rest (lift_scene.place_object). */
  placeObject(pose: ObjectPose, dropM: number): void {
    const qpos = this.data.qpos;
    const qvel = this.data.qvel;
    const a = this.objectQposAdr;
    qpos[a] = pose.x;
    qpos[a + 1] = pose.y;
    qpos[a + 2] = dropM;
    qpos[a + 3] = Math.cos(pose.yaw / 2);
    qpos[a + 4] = 0;
    qpos[a + 5] = 0;
    qpos[a + 6] = Math.sin(pose.yaw / 2);
    for (let i = 0; i < 6; i += 1) qvel[this.objectDofAdr + i] = 0;
    this.mj.mj_forward(this.model, this.data);
  }

  /** Advance one 20 fps frame. */
  stepFrame(): void {
    for (let i = 0; i < this.stepsPerFrame; i += 1) this.mj.mj_step(this.model, this.data);
  }

  /** The 12 numbers the policy sees (lift_scene.object_state). */
  objectState(): Float32Array {
    const qpos = this.data.qpos;
    const a = this.objectQposAdr;
    const r = quatToMat(qpos[a + 3], qpos[a + 4], qpos[a + 5], qpos[a + 6]);
    return Float32Array.from([
      qpos[a], qpos[a + 1], qpos[a + 2],
      r[0], r[3], r[6], // first column
      r[1], r[4], r[7], // second column
      this.objectSize[0], this.objectSize[1], this.objectSize[2],
    ]);
  }

  /**
   * The object's centre of mass in world coordinates: origin + R @ body_ipos from the current qpos,
   * as build_state_dataset.with_com_position computed it for training (data.xipos would be one
   * physics substep old right after mj_step).
   */
  objectCom(): Float64Array {
    const qpos = this.data.qpos;
    const a = this.objectQposAdr;
    const r = quatToMat(qpos[a + 3], qpos[a + 4], qpos[a + 5], qpos[a + 6]); // row-major
    const ipos = this.model.body_ipos;
    const i = 3 * this.objectBody;
    const [cx, cy, cz] = [ipos[i], ipos[i + 1], ipos[i + 2]];
    return Float64Array.from([
      qpos[a] + r[0] * cx + r[1] * cy + r[2] * cz,
      qpos[a + 1] + r[3] * cx + r[4] * cy + r[5] * cz,
      qpos[a + 2] + r[6] * cx + r[7] * cy + r[8] * cz,
    ]);
  }

  objectPose(): ObjectPose {
    const qpos = this.data.qpos;
    const a = this.objectQposAdr;
    const w = qpos[a + 3];
    const z = qpos[a + 6];
    return { x: qpos[a], y: qpos[a + 1], yaw: 2 * Math.atan2(z, w) };
  }

  /** Height of the object's base above the table (lift_scene.object_lift_m). */
  objectLift(): number {
    return this.data.qpos[this.objectQposAdr + 2];
  }

  /** z of the object's up axis: 1 standing, 0 on its side. */
  objectUpright(): number {
    const s = this.objectState();
    return s[3] * s[7] - s[4] * s[6]; // z of (x axis) x (y axis)
  }

  /** Which bodies the object touches: whether the world (table, floor) is among them, and whether anything else is. */
  objectContacts(): { table: boolean; arm: boolean } {
    const contacts = this.data.contact;
    const bodyOf = this.model.geom_bodyid;
    let table = false;
    let arm = false;
    try {
      for (let i = 0; i < this.data.ncon; i += 1) {
        const c = contacts.get(i);
        if (!c) continue;
        const b1 = bodyOf[c.geom1];
        const b2 = bodyOf[c.geom2];
        c.delete(); // every element .get() returns is its own handle
        if (b1 !== this.objectBody && b2 !== this.objectBody) continue;
        const other = b1 === this.objectBody ? b2 : b1;
        if (other === WORLD_BODY) table = true;
        else if (other !== this.objectBody) arm = true;
      }
    } finally {
      contacts.delete();
    }
    return { table, arm };
  }
}
