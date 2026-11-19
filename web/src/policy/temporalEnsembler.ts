/**
 * Temporal ensembling for ACT action chunks, ported from LeRobot 0.7.0
 * (lerobot/policies/act/modeling_act.py, ACTTemporalEnsembler).
 *
 * Every frame the policy predicts a chunk of `chunkSize` future actions. Each future step keeps a
 * running weighted average of every prediction made for it so far; older predictions weigh more
 * (w_i = exp(-coeff * i), i = 0 for the oldest). `update` takes the newest chunk, folds it into
 * the averages and returns the action for the current frame.
 */
export class TemporalEnsembler {
  private readonly weights: Float64Array;
  private readonly weightsCumsum: Float64Array;
  private averaged: Float64Array[] = []; // one action per future step, oldest step first
  private counts: number[] = []; // how many predictions each averaged action holds

  constructor(
    coeff: number,
    private readonly chunkSize: number,
    private readonly actionDim: number,
  ) {
    this.weights = new Float64Array(chunkSize);
    this.weightsCumsum = new Float64Array(chunkSize);
    let sum = 0;
    for (let i = 0; i < chunkSize; i += 1) {
      this.weights[i] = Math.exp(-coeff * i);
      sum += this.weights[i];
      this.weightsCumsum[i] = sum;
    }
  }

  reset(): void {
    this.averaged = [];
    this.counts = [];
  }

  /** `chunk` holds chunkSize * actionDim numbers, row-major (step, joint). Returns this frame's action. */
  update(chunk: ArrayLike<number>): Float64Array {
    if (chunk.length !== this.chunkSize * this.actionDim) {
      throw new Error(`expected ${this.chunkSize * this.actionDim} numbers, got ${chunk.length}`);
    }
    const row = (step: number): Float64Array =>
      Float64Array.from({ length: this.actionDim }, (_, j) => chunk[step * this.actionDim + j]);

    if (this.averaged.length === 0) {
      this.averaged = Array.from({ length: this.chunkSize }, (_, step) => row(step));
      this.counts = new Array(this.chunkSize).fill(1);
    } else {
      // After the previous pop there are chunkSize - 1 running averages; the new chunk's first
      // chunkSize - 1 steps line up with them, its last step starts a new average.
      this.averaged = this.averaged.map((average, step) => {
        const count = this.counts[step];
        const fresh = row(step);
        return average.map(
          (value, j) =>
            (value * this.weightsCumsum[count - 1] + fresh[j] * this.weights[count]) / this.weightsCumsum[count],
        );
      });
      this.counts = this.counts.map((count) => Math.min(count + 1, this.chunkSize));
      this.averaged.push(row(this.chunkSize - 1));
      this.counts.push(1);
    }
    const [action] = this.averaged;
    this.averaged = this.averaged.slice(1);
    this.counts = this.counts.slice(1);
    return action;
  }
}
