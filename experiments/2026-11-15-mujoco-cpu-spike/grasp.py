"""Scripted top-down grasp of the Lux3D object with the SO-101 position actuators.

Waypoints are solved with a small damped-least-squares IK (mj_jac) that puts the
fixed-jaw tip next to the object and points the gripper approach axis down.
"""
import sys

import mujoco
import numpy as np

from scene_builder import write_scene

ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
SEED_Q = np.array([0.0, 0.00038, 0.4735, 1.1772, 1.5844])  # Menagerie scene_box "pickup" key
GRIP_OPEN, GRIP_CLOSED = 0.9, -0.17
JAW_CLEARANCE = 0.006   # gap between fixed jaw and object side, m
TIP_HEIGHT = 0.012      # fixed-jaw tip height above floor when grasping, m
LIFT_HEIGHT = 0.12
ROLL_REG = 0.05         # keeps wrist_roll near the seed so the jaws close along +y


def solve_ik(model, data, tip_target, q0, iters=300):
    """Position of fixed-jaw tip + gripper approach (site x-axis) pointing -z."""
    tip = model.geom("fixed_jaw_sph_tip1").id
    site = model.site("gripperframe").id
    body = model.geom_bodyid[tip]
    dofs = [model.joint(j).dofadr[0] for j in ARM_JOINTS]
    q = q0.copy()
    jacp = np.zeros((3, model.nv))
    jacr = np.zeros((3, model.nv))
    for _ in range(iters):
        data.qpos[:5] = q
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        pos_err = tip_target - data.geom_xpos[tip]
        axis = data.site_xmat[site].reshape(3, 3)[:, 0]
        rot_err = np.cross(axis, np.array([0.0, 0.0, -1.0]))
        mujoco.mj_jac(model, data, jacp, jacr, data.geom_xpos[tip], body)
        J = np.vstack([jacp[:, dofs], 0.3 * jacr[:, dofs], ROLL_REG * np.eye(5)[4:5]])
        err = np.concatenate([pos_err, 0.3 * rot_err, ROLL_REG * (SEED_Q[4:5] - q[4:5])])
        dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(J.shape[0]), err)
        q = np.clip(q + 0.5 * dq, model.jnt_range[:5, 0], model.jnt_range[:5, 1])
    data.qpos[:5] = q
    mujoco.mj_kinematics(model, data)
    return q, float(np.linalg.norm(tip_target - data.geom_xpos[tip]))


def run(mesh_file="box_small.obj", render=True, ctrl_log=None):
    model = mujoco.MjModel.from_xml_path(str(write_scene(mesh_file, "scene_lux3d_grasp.xml")))
    data = mujoco.MjData(model)
    obj = model.body("lux3d_obj").id
    obj_adr = model.joint("lux3d_free").qposadr[0]

    # settle the object first (arm at zero pose)
    for _ in range(400):
        mujoco.mj_step(model, data)
    obj_pos = data.xpos[obj].copy()
    half_w = 0.5 * 0.0499  # object y-extent from prep_object.py
    side = np.array([obj_pos[0], obj_pos[1] - half_w - JAW_CLEARANCE])

    scratch = mujoco.MjData(model)
    scratch.qpos[:] = data.qpos
    q_pre, e_pre = solve_ik(model, scratch, np.r_[side, 0.09], SEED_Q)
    q_down, e_down = solve_ik(model, scratch, np.r_[side, TIP_HEIGHT], q_pre)
    q_lift, e_lift = solve_ik(model, scratch, np.r_[side, LIFT_HEIGHT], q_down)
    print(f"IK residuals (m): pre={e_pre:.4f} down={e_down:.4f} lift={e_lift:.4f}")
    print(f"q_down = {np.round(q_down, 3).tolist()}")

    plan = [  # (arm target, gripper target, seconds)
        (q_pre, GRIP_OPEN, 1.5),
        (q_down, GRIP_OPEN, 1.0),
        (q_down, GRIP_CLOSED, 1.0),
        (q_lift, GRIP_CLOSED, 1.5),
        (q_lift, GRIP_CLOSED, 1.0),
    ]
    z0 = data.xpos[obj][2]
    frames = []
    renderer = mujoco.Renderer(model, 480, 640) if render else None
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, cam)
    cam.lookat[:], cam.distance, cam.azimuth, cam.elevation = [0.17, 0.0, 0.06], 0.5, 120.0, -20.0
    start = data.ctrl.copy()
    for phase, (q_arm, grip, secs) in enumerate(plan):
        goal = np.r_[q_arm, grip]
        n = int(secs / model.opt.timestep)
        for i in range(n):
            a = min(1.0, (i + 1) / (0.7 * n))  # linear ramp, then hold
            data.ctrl[:] = (1 - a) * start + a * goal
            if ctrl_log is not None:
                ctrl_log.append(data.ctrl.tolist())
            mujoco.mj_step(model, data)
            if renderer and i % 10 == 0:
                renderer.update_scene(data, cam)
                frames.append(renderer.render().copy())
        start = goal
        print(f"phase {phase}: obj z={data.xpos[obj][2]:.4f} grip q={data.qpos[5]:.3f} ncon={data.ncon}")
    dz = data.xpos[obj][2] - z0
    print(f"object z: start {z0:.4f} -> end {data.xpos[obj][2]:.4f} (dz={dz*100:.1f} cm) "
          f"-> {'LIFTED' if dz > 0.03 else 'NOT LIFTED'}")
    if renderer:
        from PIL import Image
        imgs = [Image.fromarray(f) for f in frames]
        imgs[0].save("grasp.gif", save_all=True, append_images=imgs[1:], duration=50, loop=0)
        imgs[-1].save("render_grasp_final.png")
        renderer.close()
        print(f"wrote grasp.gif ({len(imgs)} frames) and render_grasp_final.png")
    return dz


if __name__ == "__main__":
    import json

    log = []
    run(sys.argv[1] if len(sys.argv) > 1 else "box_small.obj", ctrl_log=log)
    # settle phase (400 steps, ctrl=0) precedes these; the JS replay reproduces it
    with open("grasp_ctrl.json", "w") as fh:
        json.dump({"settle_steps": 400, "ctrl": log}, fh)
    print(f"wrote grasp_ctrl.json ({len(log)} control steps)")
