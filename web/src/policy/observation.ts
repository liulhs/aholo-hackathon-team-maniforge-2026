/**
 * The 12 object numbers handed to the policy each frame. Which variant a policy needs is set by
 * policy.json `object_position` ("origin": the object's bottom-centre point, as lift_scene.object_state;
 * "com": its centre of mass, as data/so101_state_all8_com) and the page's `lying_adapter` choice.
 */
import { LyingAdapter } from './lyingAdapter';
import type { Simulation } from '../sim/simulation';

export type ObjectPosition = 'origin' | 'com';

export interface Observer {
  /** Called at the start of every policy round. */
  reset(): void;
  observe(sim: Simulation): Float32Array;
  /** Whether the last observation described a lying object as a standing one. */
  readonly lyingView: boolean;
}

export function makeObserver(position: ObjectPosition, useLyingAdapter: boolean): Observer {
  const adapter = useLyingAdapter ? new LyingAdapter() : null;
  return {
    reset: () => adapter?.reset(),
    get lyingView() {
      return adapter?.engaged ?? false;
    },
    observe(sim: Simulation): Float32Array {
      const raw = sim.objectState();
      if (adapter && position === 'origin') return adapter.view(raw, sim.objectCom());
      if (position === 'com') raw.set(sim.objectCom().subarray(0, 3), 0);
      return raw;
    },
  };
}
