"""Read-only check of an SO-101 arm on the bus: which motor IDs 1-6 answer, and their raw positions.

Writes nothing to the motors (no torque, no calibration, no EEPROM). Use it before
`lerobot-calibrate` to see whether IDs need setting, and after calibrating to watch raw
readings while moving a joint by hand.

    conda activate lerobot
    python tools/so101_scan.py /dev/tty.usbmodem5B910285391          # one shot
    python tools/so101_scan.py /dev/tty.usbmodem5B910285391 --watch  # live, Ctrl-C to stop
"""

import argparse
import sys
import time

from lerobot.motors import SerialMotorsBus
from lerobot.motors.motors_bus import Motor, MotorNormMode

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
STS3215_MODEL_NUMBER = 777
WATCH_PERIOD_S = 0.1


def build_bus(port: str) -> SerialMotorsBus:
    motors = {
        name: Motor(motor_id, "sts3215", MotorNormMode.RANGE_M100_100)
        for motor_id, name in enumerate(JOINTS, start=1)
    }
    return SerialMotorsBus(port=port, motors=motors)


def scan(bus: SerialMotorsBus) -> list[str]:
    """Print each joint's model number; return the joints that answered."""
    present = []
    for motor_id, name in enumerate(JOINTS, start=1):
        model = bus.ping(name, num_retry=2)
        if model is None:
            print(f"  ID {motor_id} {name:<14} -- no answer")
            continue
        note = "" if model == STS3215_MODEL_NUMBER else f"  (expected {STS3215_MODEL_NUMBER} for STS3215)"
        print(f"  ID {motor_id} {name:<14} model {model}{note}")
        present.append(name)
    return present


def read_raw(bus: SerialMotorsBus, joints: list[str]) -> str:
    cells = []
    for name in joints:
        try:
            value = bus.read("Present_Position", name, normalize=False)
            cells.append(f"{name}={value:>4}")
        except (ConnectionError, RuntimeError) as exc:
            cells.append(f"{name}=ERR({exc.__class__.__name__})")
    return "  ".join(cells)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    parser.add_argument("--watch", action="store_true", help="print raw positions continuously")
    args = parser.parse_args()

    bus = build_bus(args.port)
    bus.connect(handshake=False)
    try:
        print(f"Scanning {args.port}:")
        present = scan(bus)
        print(f"{len(present)}/6 motors answered.")
        if not present:
            print("Nothing answered: check the DC power and the 3-pin chain from the board to motor 1.")
            return 1
        print("Raw positions (0-4095):", read_raw(bus, present))
        while args.watch:
            print("\r" + read_raw(bus, present), end="", flush=True)
            time.sleep(WATCH_PERIOD_S)
    except KeyboardInterrupt:
        print()
    finally:
        bus.disconnect(disable_torque=False)  # torque-off is a write; stay read-only
    return 0


if __name__ == "__main__":
    sys.exit(main())
