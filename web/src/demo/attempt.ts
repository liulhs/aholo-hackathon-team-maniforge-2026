/**
 * One grasp attempt, judged like sim/evaluate.py: the arm holds still for settleFrames while the
 * object settles, then the policy drives it; success is the object held at least liftSuccessM up
 * (and off the table) for holdSuccessS of sim time.
 *
 * Retries: with maxRetries > 0 the policy gets rounds of roundSeconds. A round that has not lifted
 * the object by then, or in which the object has lain knocked over for knockedRetryS, ends with
 * the arm driven back to its start pose (homingSeconds, a scripted move, no policy), a short
 * settle, and a fresh policy run from wherever the object now lies. The policy sees the object's
 * current pose every frame, so a new round aims at where the object is now. The last round is
 * not cut short by a knock-over (the policy sometimes picks a fallen object up). With
 * maxRetries = 0 this is the original single attempt: one round of maxSeconds.
 */

export type Phase = 'settling' | 'reaching' | 'grasping' | 'lifting' | 'recovering' | 'homing' | 'lifted' | 'missed';
export type MissReason = 'knocked-over' | 'timeout';
/** What drives the arm in the next frame. */
export type Control = 'hold' | 'policy' | 'homing';

export interface AttemptRules {
  liftSuccessM: number;
  holdSuccessS: number;
  minUpright: number;
  settleFrames: number;
  maxSeconds: number; // the single round's limit when maxRetries is 0
  knockedOverGraceS: number; // last round only: end once the object has lain knocked over this long
  maxRetries: number;
  roundSeconds: number; // each round's limit when maxRetries > 0
  knockedRetryS: number; // end a round (not the last) once the object has lain knocked over this long
  homingSeconds: number;
}

export const DEFAULT_RULES: AttemptRules = {
  liftSuccessM: 0.05,
  holdSuccessS: 1.0,
  minUpright: 0.8,
  settleFrames: 10, // evaluate.SETTLE_FRAMES
  maxSeconds: 20, // evaluate.DEFAULT_MAX_SECONDS
  knockedOverGraceS: Number.POSITIVE_INFINITY,
  maxRetries: 0,
  roundSeconds: 10,
  knockedRetryS: 3,
  homingSeconds: 1.5,
};

/**
 * What the page runs on top of DEFAULT_RULES (and tools/eval_browser.ts page mode measures).
 * Tuned on the 5-object model, 500 page trials each: no retries 345 lifted; 3 retries with 10 s
 * rounds and a 3 s knock-over trigger 367; 10 s rounds, no knock-over trigger 374; these 375.
 */
export const PAGE_RETRY_RULES: Partial<AttemptRules> = { maxRetries: 3, roundSeconds: 12, knockedRetryS: 6 };

/**
 * Whether the page describes a fallen object to the policy as a standing box (src/policy/lyingAdapter.ts).
 * Only for policies given the bottom-centre point (policy.json object_position "origin"); a
 * centre-of-mass policy gets the raw state. Measured with the origin model, 800 page trials with
 * retries: 655 without the adapter, 710 with it. The centre-of-mass model with retries: 728.
 */
export const PAGE_LYING_ADAPTER = true;

export interface ObjectReading {
  time: number; // sim time, s
  lift: number; // height of the object's base, m
  upright: number; // z of its up axis
  touchesTable: boolean;
  touchesArm: boolean;
  joints: ArrayLike<number>; // the arm's joint angles, rad
}

export interface AttemptStatus {
  phase: Phase;
  elapsed: number; // s since the policy first started (homing included)
  round: number; // 1 for the first try
  missReason?: MissReason;
  liftedAfter?: number; // s from the first policy start to success
}

const LIFTING_ABOVE_M = 0.01;
const POLICY_PHASES: ReadonlySet<Phase> = new Set(['reaching', 'grasping', 'lifting', 'recovering']);

function smoothstep(t: number): number {
  const c = Math.min(Math.max(t, 0), 1);
  return c * c * (3 - 2 * c);
}

export class Attempt {
  private settledFrames = 0;
  private firstStart: number | null = null;
  private roundStart = 0;
  private liftedSince: number | null = null;
  private knockedSince: number | null = null;
  private homing: { from: number[]; start: number } | null = null;
  private newRound = false;
  private status: AttemptStatus = { phase: 'settling', elapsed: 0, round: 1 };

  /** `home`: the arm's start pose, where homing takes it between rounds. */
  constructor(
    private readonly rules: AttemptRules = DEFAULT_RULES,
    private readonly home: ArrayLike<number> = [],
  ) {}

  get current(): AttemptStatus {
    return this.status;
  }

  get control(): Control {
    if (POLICY_PHASES.has(this.status.phase)) return 'policy';
    return this.status.phase === 'homing' ? 'homing' : 'hold';
  }

  /** Whether the policy should drive the arm in the next frame. */
  get policyActive(): boolean {
    return this.control === 'policy';
  }

  get finished(): boolean {
    return this.status.phase === 'lifted' || this.status.phase === 'missed';
  }

  /** True once per round, on the first policy frame: the caller clears the policy's action history. */
  takeNewRound(): boolean {
    const fresh = this.newRound;
    this.newRound = false;
    return fresh;
  }

  /** Joint targets while homing: a smooth move from where the round ended to the start pose. */
  homingCommand(time: number): number[] {
    if (!this.homing) return Array.from(this.home);
    const s = smoothstep((time - this.homing.start) / this.rules.homingSeconds);
    return this.homing.from.map((from, i) => from + (this.home[i] - from) * s);
  }

  private get lastRound(): boolean {
    return this.status.round > this.rules.maxRetries;
  }

  private get roundLimit(): number {
    return this.rules.maxRetries > 0 ? this.rules.roundSeconds : this.rules.maxSeconds;
  }

  /** Feed the object's state after every stepped frame; returns the updated status. */
  update(reading: ObjectReading): AttemptStatus {
    if (this.finished) return this.status;
    const { round } = this.status;
    const elapsed = this.firstStart === null ? 0 : reading.time - this.firstStart;

    if (this.status.phase === 'homing') {
      if (this.homing && reading.time - this.homing.start >= this.rules.homingSeconds) {
        this.homing = null;
        this.settledFrames = 0;
        this.status = { phase: 'settling', elapsed, round };
      } else {
        this.status = { phase: 'homing', elapsed, round };
      }
      return this.status;
    }
    if (this.status.phase === 'settling') {
      this.settledFrames += 1;
      if (this.settledFrames >= this.rules.settleFrames) {
        this.firstStart ??= reading.time;
        this.roundStart = reading.time;
        this.liftedSince = null;
        this.knockedSince = null;
        this.newRound = true;
        this.status = { phase: 'reaching', elapsed: reading.time - this.firstStart, round };
      }
      return this.status;
    }

    if (reading.lift >= this.rules.liftSuccessM && !reading.touchesTable) {
      this.liftedSince ??= reading.time;
      if (reading.time - this.liftedSince >= this.rules.holdSuccessS) {
        this.status = { phase: 'lifted', elapsed, round, liftedAfter: elapsed };
        return this.status;
      }
    } else {
      this.liftedSince = null;
    }

    const knockedOver = reading.touchesTable && reading.upright < this.rules.minUpright;
    this.knockedSince = knockedOver ? (this.knockedSince ?? reading.time) : null;
    const knockedFor = this.knockedSince === null ? 0 : reading.time - this.knockedSince;
    const inRound = reading.time - this.roundStart;
    const holding = this.liftedSince !== null; // let a lift in progress finish its hold

    if (this.lastRound) {
      const missed = (reason: MissReason): AttemptStatus => (this.status = { phase: 'missed', elapsed, round, missReason: reason });
      if (this.knockedSince !== null && knockedFor >= this.rules.knockedOverGraceS) return missed('knocked-over');
      if (inRound >= this.roundLimit && !holding) return missed(this.knockedSince !== null ? 'knocked-over' : 'timeout');
    } else if ((inRound >= this.roundLimit && !holding) || knockedFor >= this.rules.knockedRetryS) {
      this.homing = { from: Array.from(reading.joints), start: reading.time };
      this.status = { phase: 'homing', elapsed, round: round + 1 };
      return this.status;
    }

    let phase: Phase = 'reaching';
    if (knockedOver) phase = 'recovering';
    // off the table, not just a raised origin: a lying object's bottom-centre point already sits a few cm up
    else if (reading.touchesArm) phase = reading.lift > LIFTING_ABOVE_M && !reading.touchesTable ? 'lifting' : 'grasping';
    this.status = { phase, elapsed, round };
    return this.status;
  }
}
