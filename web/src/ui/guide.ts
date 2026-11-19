/**
 * The operating guide card. Open on every visit, so a first-time visitor sees how to use the
 * demo before anything else; on a phone held upright it starts folded, because open it would
 * cover the table the visitor needs to drag on. On short windows the card scrolls without a
 * visible bar, so it marks itself `data-more` while text is hidden below, and CSS fades the edge.
 */

const PHONE_QUERY = '(max-width: 720px)';
const SLACK_PX = 2; // sub-pixel rounding is not "more"

function markOverflow(guide: HTMLDetailsElement): void {
  const more = guide.open && guide.scrollTop + guide.clientHeight < guide.scrollHeight - SLACK_PX;
  guide.toggleAttribute('data-more', more);
}

export function bindGuide(guide: HTMLDetailsElement): void {
  guide.open = !window.matchMedia(PHONE_QUERY).matches;
  const update = (): void => markOverflow(guide);
  guide.addEventListener('toggle', update);
  guide.addEventListener('scroll', update, { passive: true });
  new ResizeObserver(update).observe(guide);
  update();
}
