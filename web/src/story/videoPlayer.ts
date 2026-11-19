/**
 * The story's own video controls, in place of the browser's: a large play button over the frame,
 * and a bar with play/pause, a draggable progress bar and the time. Applied to every
 * <figure class="player"> that holds a <video>; the HTML keeps `controls` so the video still has
 * the browser's controls if this script never runs. All the clips are silent, so there is no
 * volume control.
 *
 * The clips play by themselves, looping, while at least half of one is on screen, and pause when it
 * scrolls away (so off-screen video costs nothing). Once the visitor pauses a clip it stays paused.
 * With reduced motion they do not autoplay; the play button is there instead.
 */

const SEEK_STEPS = 1000;
const VISIBLE_SHARE = 0.5;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  return node;
}

function clock(seconds: number): string {
  if (!Number.isFinite(seconds)) return '0:00';
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function enhance(figure: HTMLElement, video: HTMLVideoElement, autoplay: IntersectionObserver): void {
  video.controls = false;
  video.playsInline = true;
  video.muted = true; // browsers only autoplay muted video
  video.loop = true;

  const frame = el('div', 'player__frame');
  video.replaceWith(frame);
  frame.append(video);

  const big = el('button', 'player__big');
  big.type = 'button';
  big.setAttribute('aria-label', '播放');

  const bar = el('div', 'player__bar');
  const toggle = el('button', 'player__toggle');
  toggle.type = 'button';
  toggle.setAttribute('aria-label', '播放');
  const seek = el('input', 'player__seek');
  seek.type = 'range';
  seek.min = '0';
  seek.max = String(SEEK_STEPS);
  seek.step = '1';
  seek.value = '0';
  seek.setAttribute('aria-label', '播放进度');
  const time = el('span', 'player__time');
  time.textContent = '0:00 / 0:00';
  bar.append(toggle, seek, time);
  frame.append(big, bar);

  const playOrPause = (): void => {
    if (video.paused || video.ended) {
      delete figure.dataset.userPaused;
      start(figure, video);
    } else {
      figure.dataset.userPaused = 'true'; // autoplay leaves it alone from now on
      video.pause();
    }
  };

  const showTime = (): void => {
    const fraction = video.duration ? video.currentTime / video.duration : 0;
    seek.value = String(Math.round(fraction * SEEK_STEPS));
    seek.style.setProperty('--progress', String(fraction));
    const text = `${clock(video.currentTime)} / ${clock(video.duration)}`;
    time.textContent = text;
    seek.setAttribute('aria-valuetext', text);
  };

  const showState = (): void => {
    const state = video.ended ? 'ended' : video.paused ? 'paused' : 'playing';
    figure.dataset.state = state;
    const label = state === 'playing' ? '暂停' : state === 'ended' ? '重新播放' : '播放';
    toggle.setAttribute('aria-label', label);
    big.setAttribute('aria-label', label);
  };

  big.addEventListener('click', playOrPause);
  toggle.addEventListener('click', playOrPause);
  video.addEventListener('click', playOrPause);
  seek.addEventListener('input', () => {
    if (video.duration) video.currentTime = (Number(seek.value) / SEEK_STEPS) * video.duration;
    showTime();
  });
  video.addEventListener('timeupdate', showTime);
  video.addEventListener('loadedmetadata', showTime);
  video.addEventListener('durationchange', showTime);
  for (const event of ['play', 'pause', 'ended']) video.addEventListener(event, showState);

  showState();
  showTime();
  autoplay.observe(figure);
}

function start(figure: HTMLElement, video: HTMLVideoElement): void {
  video.play().catch((error: unknown) => {
    if (error instanceof DOMException && error.name === 'AbortError') return; // paused again before it began
    figure.dataset.state = 'error';
    figure.title = `视频无法播放：${error instanceof Error ? error.message : String(error)}`;
  });
}

/** Plays a clip while it is on screen and pauses it when it leaves, unless the visitor paused it. */
function autoplayObserver(): IntersectionObserver {
  return new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const figure = entry.target as HTMLElement;
        const video = figure.querySelector('video');
        if (!video || figure.dataset.userPaused || reducedMotion.matches) continue;
        if (entry.isIntersecting) start(figure, video);
        else video.pause();
      }
    },
    { threshold: VISIBLE_SHARE },
  );
}

export function bindVideoPlayers(): void {
  const autoplay = autoplayObserver();
  document.querySelectorAll<HTMLElement>('figure.player').forEach((figure) => {
    const video = figure.querySelector('video');
    if (video) enhance(figure, video, autoplay);
  });
}
