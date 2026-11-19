"""Drive the MuJoCo SO-101 with the real, calibrated SO-101 arm (torque off, moved by hand).

macOS needs `mjpython` for the live viewer:

    source .venv/bin/activate
    mjpython sim/teleop.py                    # real arm -> simulated arm, with physics
    mjpython sim/teleop.py --mirror           # copy joint angles straight in (no physics), for checking directions
    mjpython sim/teleop.py --demo             # no arm: sweep each joint, to check the viewer works

Close the viewer window or press Ctrl-C to stop.
"""

import argparse
import math
import time
from pathlib import Path
from typing import Callable

import mujoco
import mujoco.viewer

from so101_mapping import JOINT_NAMES, clip, readings_to_joint_rad

SIM_DIR = Path(__file__).parent
DEFAULT_SCENE = SIM_DIR / "models" / "so101" / "scene_nocam.xml"  # no wrist camera mount; see make_nocam_model.py
DEFAULT_PORT = "/dev/tty.usbmodem5B910285391"
DEFAULT_ARM_ID = "arm_a"
CONTROL_HZ = 50
STATUS_PERIOD_S = 0.5
DEMO_PERIOD_S = 4.0
DEMO_AMPLITUDE_RAD = 0.6


def connect_arm(port: str, arm_id: str):
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    arm = SO101Leader(SO101LeaderConfig(port=port, id=arm_id))
    arm.connect(calibrate=False)
    if not arm.is_calibrated:
        arm.disconnect()
        raise SystemExit(f"No calibration for '{arm_id}'. Run lerobot-calibrate --teleop.id={arm_id} first.")
    return arm


def demo_source(start: float) -> Callable[[], dict[str, float]]:
    """Fake arm: one joint at a time swings back and forth."""

    def read() -> dict[str, float]:
        t = time.monotonic() - start
        active = int(t // DEMO_PERIOD_S) % len(JOINT_NAMES)
        swing = DEMO_AMPLITUDE_RAD * math.sin(2 * math.pi * t / DEMO_PERIOD_S)
        return {name: (swing if i == active else 0.0) for i, name in enumerate(JOINT_NAMES)}

    return read


class SimArm:
    """Name-indexed access to the model's joints and position actuators."""

    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData) -> None:
        self.model, self.data = model, data
        self.qpos_adr = {name: int(model.joint(name).qposadr[0]) for name in JOINT_NAMES}
        self.ctrl_idx = {name: int(model.actuator(name).id) for name in JOINT_NAMES}

    def command(self, angles: dict[str, float]) -> None:
        for name, angle in angles.items():
            low, high = self.model.actuator_ctrlrange[self.ctrl_idx[name]]
            self.data.ctrl[self.ctrl_idx[name]] = clip(angle, low, high)

    def place(self, angles: dict[str, float]) -> None:
        """Set joint positions directly and zero velocities (mirror mode and the first frame)."""
        for name, angle in angles.items():
            self.data.qpos[self.qpos_adr[name]] = angle
        self.data.qvel[:] = 0
        self.command(angles)
        mujoco.mj_forward(self.model, self.data)

    def joint_deg(self) -> dict[str, float]:
        return {name: math.degrees(self.data.qpos[adr]) for name, adr in self.qpos_adr.items()}


def status_line(target: dict[str, float], sim: dict[str, float]) -> str:
    cells = [f"{name[:11]:>11} {math.degrees(target[name]):6.1f}/{sim[name]:6.1f}" for name in JOINT_NAMES]
    return "target/sim deg | " + " | ".join(cells)


def run(read_angles: Callable[[], dict[str, float]], scene: Path, mirror: bool) -> None:
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    arm = SimArm(model, data)
    arm.place(read_angles())
    steps_per_tick = max(1, round(1.0 / CONTROL_HZ / model.opt.timestep))
    next_status = 0.0

    with mujoco.viewer.launch_passive(model, data) as viewer:
        while viewer.is_running():
            tick_start = time.monotonic()
            target = read_angles()
            if mirror:
                arm.place(target)
            else:
                arm.command(target)
                for _ in range(steps_per_tick):
                    mujoco.mj_step(model, data)
            viewer.sync()
            if tick_start >= next_status:
                print("\r" + status_line(target, arm.joint_deg()), end="", flush=True)
                next_status = tick_start + STATUS_PERIOD_S
            time.sleep(max(0.0, 1.0 / CONTROL_HZ - (time.monotonic() - tick_start)))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--id", default=DEFAULT_ARM_ID, help="calibration name used with lerobot-calibrate")
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--mirror", action="store_true", help="copy angles in directly, no physics")
    parser.add_argument("--demo", action="store_true", help="no arm: sweep the joints one by one")
    args = parser.parse_args()

    if not args.scene.exists():
        raise SystemExit(f"{args.scene} not found. Run: bash sim/fetch_models.sh")

    if args.demo:
        run(demo_source(time.monotonic()), args.scene, args.mirror)
        return

    real_arm = connect_arm(args.port, args.id)
    try:
        run(lambda: readings_to_joint_rad(real_arm.get_action()), args.scene, args.mirror)
    except KeyboardInterrupt:
        print()
    finally:
        real_arm.disconnect()


if __name__ == "__main__":
    main()
