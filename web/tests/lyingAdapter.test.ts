/** lyingView against the tipped-start experiment's Python shim("F") on random states (tests/lying_view_cases.json). */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { LyingAdapter, lyingView } from '../src/policy/lyingAdapter';

interface Case {
  state: number[];
  com: number[];
  expected: number[];
}

const cases = JSON.parse(readFileSync(new URL('./lying_view_cases.json', import.meta.url), 'utf8')) as Case[];

test('lyingView matches the Python shim F', () => {
  for (const c of cases) {
    const got = lyingView(c.state, c.com);
    got.forEach((v, i) => assert.ok(Math.abs(v - c.expected[i]) < 1e-6, `index ${i}: ${v} vs ${c.expected[i]}`));
  }
});

test('the adapter passes standing objects through and switches with hysteresis', () => {
  const standing = Float32Array.from([0.2, 0, 0, 1, 0, 0, 0, 1, 0, 0.04, 0.03, 0.09]);
  const lying = Float32Array.from([0.2, 0, 0.02, 1, 0, 0, 0, 0, 1, 0.04, 0.03, 0.09]); // y axis up: on its side
  const halfway = Float32Array.from([0.2, 0, 0, 1, 0, 0, 0, 0.85, 0.527, 0.04, 0.03, 0.09]); // upright 0.85
  const adapter = new LyingAdapter();
  assert.equal(adapter.view(standing, [0.2, 0, 0.04]), standing);
  assert.equal(adapter.view(halfway, [0.2, 0, 0.04]), halfway);
  assert.notEqual(adapter.view(lying, [0.25, 0, 0.02]), lying);
  assert.equal(adapter.engaged, true);
  assert.notEqual(adapter.view(halfway, [0.2, 0, 0.04]), halfway); // still engaged until 0.9
  assert.equal(adapter.view(standing, [0.2, 0, 0.04]), standing);
  assert.equal(adapter.engaged, false);
});
