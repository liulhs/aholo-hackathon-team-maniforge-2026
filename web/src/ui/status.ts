/** The status line under the scene: what the arm is doing, in short formal labels. */
import type { AttemptStatus, Phase } from '../demo/attempt';

export type StatusPhase = Phase | 'loading' | 'placing' | 'error';

const TEXT: Record<Exclude<StatusPhase, 'lifted' | 'missed'>, string> = {
  loading: '载入中',
  placing: '松开后开始抓取',
  settling: '已放置，准备抓取',
  reaching: '接近物体',
  grasping: '接触物体，夹取中',
  lifting: '抬升中',
  recovering: '物体倾倒，继续尝试',
  homing: '未抓取成功，机械臂复位',
  error: '载入失败',
};

export function describe(status: AttemptStatus): string {
  const tries = status.round > 1 ? `（共尝试 ${status.round} 次）` : '';
  if (status.phase === 'lifted') return `已拿起，用时 ${(status.liftedAfter ?? status.elapsed).toFixed(1)} 秒${tries}`;
  if (status.phase === 'missed') {
    const what = status.missReason === 'knocked-over' ? '物体倾倒，抓取失败' : '抓取失败';
    return `${what}${tries}。可拖动物体调整位置后重试`;
  }
  if (status.phase === 'homing') return TEXT.homing;
  if (status.round > 1 && (status.phase === 'settling' || status.phase === 'reaching')) {
    return `第 ${status.round} 次尝试：${TEXT[status.phase]}`;
  }
  return TEXT[status.phase];
}

export class StatusLine {
  constructor(
    private readonly element: HTMLElement,
    private readonly text: HTMLElement,
  ) {}

  private lastText = '';

  show(phase: StatusPhase, text?: string): void {
    const message = text ?? (phase === 'lifted' || phase === 'missed' ? '' : TEXT[phase]);
    if (this.element.dataset.phase !== phase) this.element.dataset.phase = phase;
    if (message !== this.lastText) {
      this.text.textContent = message; // only on change, so screen readers hear each step once
      this.lastText = message;
    }
  }

  showAttempt(status: AttemptStatus): void {
    this.show(status.phase, describe(status));
  }
}
