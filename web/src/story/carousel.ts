/**
 * The story's carousels: a scroll-snap track of full-width slides, so touch swipes and trackpads
 * work natively; arrows and dots scroll it. Autoplay is timed by the active dot's fill animation
 * (CSS): when it ends, the next slide comes in. Pausing pauses that animation; with reduced motion
 * there is no animation, so no autoplay. It also holds while hovered by a mouse, while keyboard
 * focus is inside, while mostly off screen, and while the tab is hidden.
 *
 * Markup inside `root`: .carousel__track (slides as children), .carousel__dots (empty <ol>),
 * .carousel__prev, .carousel__next, .carousel__play.
 */

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  return node;
}

function part<T extends HTMLElement>(root: HTMLElement, selector: string): T {
  const node = root.querySelector<T>(selector);
  if (!node) throw new Error(`carousel is missing ${selector}`);
  return node;
}

/** `labels` names each slide for its dot, e.g. the object shown. */
export function bindCarousel(root: HTMLElement, labels: readonly string[]): void {
  const track = part<HTMLOListElement>(root, '.carousel__track');
  const dotList = part<HTMLOListElement>(root, '.carousel__dots');
  const play = part<HTMLButtonElement>(root, '.carousel__play');
  const total = labels.length;

  const dots = labels.map((label, i) => {
    const button = el('button', 'carousel__dot');
    button.type = 'button';
    button.setAttribute('aria-label', `第 ${i + 1} 个：${label}`);
    button.append(el('span', 'carousel__dot-fill'));
    button.addEventListener('click', () => go(i));
    const entry = el('li', '');
    entry.append(button);
    dotList.append(entry);
    return button;
  });

  /** Distance from one slide to the next: a track width plus the CSS gap between slides. */
  const pitch = (): number => {
    const [first, second] = track.children as HTMLCollectionOf<HTMLElement>;
    return second ? second.offsetLeft - first.offsetLeft : track.clientWidth;
  };

  let current = 0;
  let userPaused = false;
  const holds = new Set<string>();

  const syncPlaying = (): void => {
    root.dataset.playing = String(!userPaused && holds.size === 0);
    play.setAttribute('aria-pressed', String(userPaused));
    play.textContent = userPaused ? '播放' : '暂停';
  };

  const mark = (index: number): void => {
    if (index === current && dots[index].hasAttribute('aria-current')) return;
    current = index;
    dots.forEach((dot, i) => (i === index ? dot.setAttribute('aria-current', 'true') : dot.removeAttribute('aria-current')));
    const fill = dots[index].firstElementChild as HTMLElement; // restart this dot's timer
    fill.style.animation = 'none';
    void fill.offsetWidth;
    fill.style.animation = '';
  };

  function go(index: number): void {
    const target = (index + total) % total;
    track.scrollTo({ left: target * pitch(), behavior: 'smooth' });
    mark(target);
  }

  // the slide nearest the track's left edge is current, however the track got there
  let settle = 0;
  track.addEventListener(
    'scroll',
    () => {
      window.clearTimeout(settle);
      settle = window.setTimeout(() => mark(Math.min(total - 1, Math.round(track.scrollLeft / pitch()))), 80);
    },
    { passive: true },
  );

  dots.forEach((dot) =>
    dot.firstElementChild?.addEventListener('animationend', () => {
      if (dot.hasAttribute('aria-current')) go(current + 1);
    }),
  );
  part(root, '.carousel__prev').addEventListener('click', () => go(current - 1));
  part(root, '.carousel__next').addEventListener('click', () => go(current + 1));
  play.addEventListener('click', () => {
    userPaused = !userPaused;
    syncPlaying();
  });
  track.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    go(current + (e.key === 'ArrowRight' ? 1 : -1));
  });

  const hold = (reason: string, on: boolean): void => {
    if (on) holds.add(reason);
    else holds.delete(reason);
    syncPlaying();
  };
  root.addEventListener('pointerenter', (e) => e.pointerType === 'mouse' && hold('hover', true));
  root.addEventListener('pointerleave', () => hold('hover', false));
  root.addEventListener('focusin', () => hold('focus', root.matches(':has(:focus-visible)')));
  root.addEventListener('focusout', () => hold('focus', false));
  document.addEventListener('visibilitychange', () => hold('hidden', document.hidden));
  new IntersectionObserver(([entry]) => hold('offscreen', !entry.isIntersecting), { threshold: 0.35 }).observe(root);

  mark(0);
  syncPlaying();
}
