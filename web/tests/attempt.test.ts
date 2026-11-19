/** Run: cd web && npm test */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Attempt, DEFAULT_RULES, type AttemptRules, type ObjectReading } from '../src/demo/attempt';

const FPS = 20;
const HOME = [0, 0, 0, 0, 0, 0];
const AWAY = [1, 1, 1, 1, 1, 1];

function reading(frame: number, over: Partial<ObjectReading> = {}): ObjectReading {
  return { time: frame / FPS, lift: 0, upright: 1, touchesTable: true, touchesArm: false, joints: AWAY, ...over };
}

/** Feed `frames` frames from `from`, each made by `make`; returns the next frame number. */
function feed(attempt: Attempt, from: number, frames: number, make: (f: number) => ObjectReading = reading): number {
  for (let f = from; f < from + frames; f += 1) attempt.update(make(f));
  return from + frames;
}

const RETRY: AttemptRules = { ...DEFAULT_RULES, maxRetries: 2, roundSeconds: 5, knockedRetryS: 1, homingSeconds: 1 };

test('without retries a round lasts maxSeconds and ends as a timeout', () => {
  const attempt = new Attempt(DEFAULT_RULES, HOME);
  let f = feed(attempt, 0, DEFAULT_RULES.settleFrames);
  assert.equal(attempt.control, 'policy');
  f = feed(attempt, f, DEFAULT_RULES.maxSeconds * FPS - 1);
  assert.equal(attempt.finished, false);
  feed(attempt, f, 1);
  assert.equal(attempt.current.phase, 'missed');
  assert.equal(attempt.current.missReason, 'timeout');
  assert.equal(attempt.current.round, 1);
});

test('a round that runs out homes the arm, settles, and starts a new policy round', () => {
  const attempt = new Attempt(RETRY, HOME);
  let f = feed(attempt, 0, RETRY.settleFrames);
  assert.equal(attempt.takeNewRound(), true);
  assert.equal(attempt.takeNewRound(), false);
  f = feed(attempt, f, RETRY.roundSeconds * FPS);
  assert.equal(attempt.current.phase, 'homing');
  assert.equal(attempt.control, 'homing');
  assert.equal(attempt.current.round, 2);
  const start = f / FPS - 1 / FPS;
  assert.deepEqual(attempt.homingCommand(start), AWAY);
  assert.deepEqual(attempt.homingCommand(start + RETRY.homingSeconds), HOME);
  const mid = attempt.homingCommand(start + RETRY.homingSeconds / 2);
  assert.ok(mid.every((v) => Math.abs(v - 0.5) < 1e-9));
  f = feed(attempt, f, RETRY.homingSeconds * FPS);
  assert.equal(attempt.current.phase, 'settling');
  f = feed(attempt, f, RETRY.settleFrames);
  assert.equal(attempt.control, 'policy');
  assert.equal(attempt.takeNewRound(), true);
});

test('a knock-over ends a round early, but not the last one', () => {
  const attempt = new Attempt(RETRY, HOME);
  const knocked = (frame: number): ObjectReading => reading(frame, { upright: 0.1 });
  let f = feed(attempt, 0, RETRY.settleFrames);
  f = feed(attempt, f, RETRY.knockedRetryS * FPS + 1, knocked);
  assert.equal(attempt.current.phase, 'homing');
  // rounds 2 and 3
  for (let round = 2; round <= 3; round += 1) {
    f = feed(attempt, f, RETRY.homingSeconds * FPS + RETRY.settleFrames);
    assert.equal(attempt.current.round, round);
    assert.equal(attempt.control, 'policy');
    if (round === 2) f = feed(attempt, f, RETRY.knockedRetryS * FPS + 1, knocked);
  }
  // last round: lying knocked over keeps the policy going until the round limit
  f = feed(attempt, f, RETRY.roundSeconds * FPS - 1, knocked);
  assert.equal(attempt.current.phase, 'recovering');
  feed(attempt, f, 1, knocked);
  assert.equal(attempt.current.phase, 'missed');
  assert.equal(attempt.current.missReason, 'knocked-over');
  assert.equal(attempt.current.round, 3);
});

test('a lift held for holdSuccessS succeeds and reports the round and total time', () => {
  const attempt = new Attempt(RETRY, HOME);
  let f = feed(attempt, 0, RETRY.settleFrames);
  f = feed(attempt, f, RETRY.roundSeconds * FPS); // round 1 runs out
  f = feed(attempt, f, RETRY.homingSeconds * FPS + RETRY.settleFrames);
  const lifted = (frame: number): ObjectReading => reading(frame, { lift: 0.08, touchesTable: false, touchesArm: true });
  feed(attempt, f, RETRY.holdSuccessS * FPS + 1, lifted);
  assert.equal(attempt.current.phase, 'lifted');
  assert.equal(attempt.current.round, 2);
  assert.ok((attempt.current.liftedAfter ?? 0) > RETRY.roundSeconds + RETRY.homingSeconds);
});

test('a lift in progress at the round limit is allowed to finish its hold', () => {
  const attempt = new Attempt(RETRY, HOME);
  let f = feed(attempt, 0, RETRY.settleFrames);
  f = feed(attempt, f, RETRY.roundSeconds * FPS - 5);
  const lifted = (frame: number): ObjectReading => reading(frame, { lift: 0.08, touchesTable: false, touchesArm: true });
  feed(attempt, f, RETRY.holdSuccessS * FPS + 1, lifted);
  assert.equal(attempt.current.phase, 'lifted');
  assert.equal(attempt.current.round, 1);
});
