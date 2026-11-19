"""Give an assembled SO-101's motors IDs 1-6 one link at a time, without taking the arm apart.

New STS3215 motors all answer as ID 1, so six of them on one bus talk over each other and
nothing answers cleanly. `lerobot-setup-motors` wants each motor alone on the board, which
on an assembled arm means a long cable to every joint. This script needs only the chain:

  1. Unplug the link from motor 1 to motor 2, so motor 1 (base) is alone. It becomes ID 100
     for now, so the next new motor can be told apart.
  2. For k = 2..6: plug the link (k-1)->k back and, unless k is the gripper, unplug the
     link k->(k+1). Exactly one motor then answers as ID 1: motor k. It becomes ID k.
  3. Motor 1 goes from 100 back to 1.

Every step scans the bus first and refuses to write unless it sees exactly what it expects.
It can be re-run; it picks up from what the scan shows. Unplug DC power before touching a
link, plug it back before pressing Enter.

    conda activate lerobot
    python tools/so101_assign_ids.py /dev/tty.usbmodem5B910285391
"""

import argparse
import sys

from lerobot.motors import SerialMotorsBus
from lerobot.motors.motors_bus import Motor, MotorNormMode

FACTORY_ID = 1
TEMP_ID_FOR_BASE = 100
STS3215_MODEL_NUMBER = 777
FINAL_IDS = (1, 2, 3, 4, 5, 6)
JOINT_NAMES = {1: "shoulder_pan", 2: "shoulder_lift", 3: "elbow_flex", 4: "wrist_flex", 5: "wrist_roll", 6: "gripper"}
SCAN_ATTEMPTS = 3


class Bus:
    """The open port, a scan of every ID, and an ID change."""

    def __init__(self, port: str) -> None:
        self._bus = SerialMotorsBus(port=port, motors={"probe": Motor(1, "sts3215", MotorNormMode.RANGE_M100_100)})
        self._bus.connect(handshake=False)
        self._definition = self._bus._definition("probe")

    def scan(self) -> dict[int, int]:
        """IDs that answer, as {id: model}; the largest of a few scans, since one can drop a reply."""
        results = [self._bus._scan(self._definition) for _ in range(SCAN_ATTEMPTS)]
        return max(results, key=len)

    def change_id(self, old_id: int, new_id: int) -> None:
        self._bus._connected_bus.change_id(self._definition, old_id, new_id)
        found = self.scan()
        if new_id not in found or old_id in found:
            raise RuntimeError(f"ID {old_id} -> {new_id} did not take: bus now shows {sorted(found)}")

    def close(self) -> None:
        self._bus.disconnect(disable_torque=False)


def wait_for_user(message: str) -> None:
    print()
    print(message)
    input("Press Enter when done (Ctrl-C to stop)... ")


def describe(found: dict[int, int]) -> str:
    if not found:
        return "nothing answered"
    return ", ".join(f"ID {motor_id} (model {model})" for motor_id, model in sorted(found.items()))


def check_models(found: dict[int, int]) -> None:
    wrong = {motor_id: model for motor_id, model in found.items() if model != STS3215_MODEL_NUMBER}
    if wrong:
        raise RuntimeError(f"Not STS3215 (model {STS3215_MODEL_NUMBER}): {wrong}")


def isolate_base(bus: Bus) -> None:
    """Step 1: motor 1 alone on the bus at the factory ID becomes the temporary ID."""
    while True:
        found = bus.scan()
        if TEMP_ID_FOR_BASE in found:
            print(f"Base motor already at temporary ID {TEMP_ID_FOR_BASE}.")
            return
        if set(found) == {FACTORY_ID}:
            check_models(found)
            bus.change_id(FACTORY_ID, TEMP_ID_FOR_BASE)
            print(f"Base motor (shoulder_pan): ID {FACTORY_ID} -> {TEMP_ID_FOR_BASE} (temporary).")
            return
        print(f"Bus shows: {describe(found)}. Expected only ID {FACTORY_ID}.")
        wait_for_user(
            "Unplug DC power. Unplug the 3-pin link between motor 1 (base) and motor 2, keep the board -> "
            "motor 1 cable. Plug DC power back."
        )


def add_link(bus: Bus, target_id: int) -> None:
    """Steps 2-6: the one motor newly on the bus at the factory ID becomes `target_id`."""
    name = JOINT_NAMES[target_id]
    while True:
        found = bus.scan()
        if target_id in found and FACTORY_ID not in found:
            print(f"{name} already at ID {target_id}.")
            return
        if FACTORY_ID in found:
            check_models(found)
            bus.change_id(FACTORY_ID, target_id)
            print(f"{name}: ID {FACTORY_ID} -> {target_id}.")
            return
        print(f"Bus shows: {describe(found)}. Expected one new motor at ID {FACTORY_ID}.")
        wait_for_user(
            f"Unplug DC power. Plug in the link from motor {target_id - 1} to motor {target_id} ({name})"
            + (f" and unplug the link from motor {target_id} to motor {target_id + 1}" if target_id < 6 else "")
            + ". Plug DC power back. (Motors past the open link still at ID 1 would collide with it.)"
        )


def restore_base(bus: Bus) -> None:
    found = bus.scan()
    if TEMP_ID_FOR_BASE in found:
        bus.change_id(TEMP_ID_FOR_BASE, FACTORY_ID)
        print(f"Base motor: ID {TEMP_ID_FOR_BASE} -> {FACTORY_ID}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port")
    args = parser.parse_args()

    bus = Bus(args.port)
    try:
        found = bus.scan()
        print(f"Bus now: {describe(found)}")
        if set(found) == set(FINAL_IDS):
            check_models(found)
            print("IDs 1-6 all answer already. Nothing to do.")
            return 0
        isolate_base(bus)
        for target_id in FINAL_IDS[1:]:
            add_link(bus, target_id)
        restore_base(bus)
        found = bus.scan()
        print(f"Done. Bus now: {describe(found)}")
        return 0 if set(found) == set(FINAL_IDS) else 1
    except KeyboardInterrupt:
        print("\nStopped. Re-run to continue from where the bus is now.")
        return 1
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
