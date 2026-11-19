/**
 * One 20 fps frame of an attempt: pick the arm's command (policy, homing move, or nothing), step
 * the physics, and judge. Shared by the page (src/main.ts) and the evaluation harness
 * (tools/eval_browser.ts), so the measured success rate is what visitors see.
 */
import type { Attempt, AttemptStatus } from './attempt';
import type { Observer } from '../policy/observation';
import type { Simulation } from '../sim/simulation';

export interface FramePolicy {
  reset(): void;
  act(jointRad: ArrayLike<number>, objectState: ArrayLike<number>): Promise<Float64Array>;
}

/**
 * Returns the attempt's status after the frame, or null when there was no attempt to judge or
 * `stillCurrent()` turned false while the policy ran (the page swapped scene or attempt meanwhile).
 */
export async function attemptFrame(
  sim: Simulation,
  policy: FramePolicy,
  attempt: Attempt | null,
  stillCurrent: () => boolean = () => true,
  observer: Observer | null = null,
): Promise<AttemptStatus | null> {
  if (attempt?.control === 'policy') {
    if (attempt.takeNewRound()) {
      policy.reset();
      observer?.reset();
    }
    const action = await policy.act(sim.jointAngles(), observer ? observer.observe(sim) : sim.objectState());
    if (!stillCurrent()) return null;
    sim.command(action);
  } else if (attempt?.control === 'homing') {
    sim.command(attempt.homingCommand(sim.time));
  }
  sim.stepFrame();
  if (!attempt || attempt.finished) return null;
  const contacts = sim.objectContacts();
  return attempt.update({
    time: sim.time,
    lift: sim.objectLift(),
    upright: sim.objectUpright(),
    touchesTable: contacts.table,
    touchesArm: contacts.arm,
    joints: sim.jointAngles(),
  });
}
