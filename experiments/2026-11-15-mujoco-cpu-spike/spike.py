"""CPU feasibility spike: SO-101 (MuJoCo Menagerie) + Lux3D object.

Steps: (1) benchmark arm-only scene, (2) build arm + object scenes,
(3) settle the object for 2 s and report resting height / velocity,
(4) render one offscreen PNG.
"""
import time

import mujoco
import numpy as np

from scene_builder import MODEL_DIR, write_scene

SIM_SECONDS = 2.0
BENCH_REPEATS = 5


def compile_model(path):
    t0 = time.perf_counter()
    model = mujoco.MjModel.from_xml_path(str(path))
    return model, time.perf_counter() - t0


def realtime_factor(model, seconds=SIM_SECONDS, keyframe=None):
    """Best-of-N wall-clock realtime factor for `seconds` of sim time."""
    data = mujoco.MjData(model)
    n_steps = int(round(seconds / model.opt.timestep))
    best = np.inf
    for _ in range(BENCH_REPEATS):
        if keyframe is None:
            mujoco.mj_resetData(model, data)
        else:
            mujoco.mj_resetDataKeyframe(model, data, keyframe)
        t0 = time.perf_counter()
        for _ in range(n_steps):
            mujoco.mj_step(model, data)
        best = min(best, time.perf_counter() - t0)
    return seconds / best, n_steps, best


def settle(model):
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.ctrl[:] = 0.0
    obj = model.body("lux3d_obj").id
    for _ in range(int(round(SIM_SECONDS / model.opt.timestep))):
        mujoco.mj_step(model, data)
    lin_speed = np.linalg.norm(data.cvel[obj][3:])
    ang_speed = np.linalg.norm(data.cvel[obj][:3])
    return data, data.xpos[obj].copy(), lin_speed, ang_speed


def render_png(model, data, path, camera=None):
    from PIL import Image

    with mujoco.Renderer(model, height=720, width=960) as renderer:
        cam = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(model, cam)
        cam.lookat[:] = [0.15, 0.0, 0.08]
        cam.distance, cam.azimuth, cam.elevation = 0.55, 135.0, -25.0
        renderer.update_scene(data, camera=camera if camera else cam)
        Image.fromarray(renderer.render()).save(path)


def main():
    print(f"mujoco {mujoco.__version__}")
    arm, t_arm = compile_model(MODEL_DIR / "scene.xml")
    rtf, n, wall = realtime_factor(arm)
    print(f"[arm only] compile {t_arm*1e3:.1f} ms, nq={arm.nq} nu={arm.nu} dt={arm.opt.timestep}")
    print(f"[arm only] {n} steps ({SIM_SECONDS}s sim) in {wall*1e3:.1f} ms -> {rtf:.0f}x realtime")

    results = {}
    for label, mesh in [("full 276k faces", "box_full.obj"), ("decimated 4k faces", "box_small.obj")]:
        path = write_scene(mesh, f"scene_lux3d_{mesh.split('.')[0]}.xml")
        model, t_c = compile_model(path)
        rtf, n, wall = realtime_factor(model)
        data, pos, v, w = settle(model)
        geom = model.geom("lux3d_obj")
        print(f"[{label}] compile {t_c*1e3:.0f} ms; hull-collided mesh; body mass={model.body('lux3d_obj').mass[0]:.3f} kg")
        print(f"[{label}] {n} steps in {wall*1e3:.1f} ms -> {rtf:.0f}x realtime")
        print(f"[{label}] after 2 s: obj center z={pos[2]:.4f} m (half-height 0.025), "
              f"|v|={v:.2e} m/s |w|={w:.2e} rad/s, ncon={data.ncon}, geom size={np.round(geom.size,4)}")
        results[mesh] = (model, data)

    model, data = results["box_small.obj"]
    try:
        render_png(model, data, "render_settled.png")
        print("rendered render_settled.png")
    except Exception as exc:  # report, do not hide, renderer failures
        print(f"render failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
