/**
 * A `matchMedia` stand-in for the compact crossover (FRG-UI-018, FRG-UI-049).
 * jsdom implements no media queries at all, so a test that needs the narrow
 * presentation must install one. Only `(max-width: Npx)` is interpreted — the
 * single query shape the app uses; anything else reports no match rather than
 * silently pretending to evaluate.
 *
 * Install nothing by default: with `matchMedia` absent the app renders its wide
 * frame, which is what every test that does not opt in expects.
 */

type ChangeListener = (event: MediaQueryListEvent) => void;

const MAX_WIDTH_RE = /^\(max-width:\s*([\d.]+)px\)$/;

let viewportWidth = 1024;
let installed = false;
const lists = new Set<FakeMediaQueryList>();

class FakeMediaQueryList {
  readonly media: string;
  matches = false;
  private readonly listeners = new Set<ChangeListener>();

  constructor(media: string) {
    this.media = media;
    this.evaluate();
  }

  /** Recompute `matches`; returns true when the value changed. */
  evaluate(): boolean {
    const parsed = MAX_WIDTH_RE.exec(this.media);
    const next = parsed !== null && viewportWidth <= Number(parsed[1]);
    const changed = next !== this.matches;
    this.matches = next;
    return changed;
  }

  notify(): void {
    const event = { matches: this.matches, media: this.media } as MediaQueryListEvent;
    for (const listener of this.listeners) listener(event);
  }

  addEventListener(_type: 'change', listener: ChangeListener): void {
    this.listeners.add(listener);
  }

  removeEventListener(_type: 'change', listener: ChangeListener): void {
    this.listeners.delete(listener);
  }
}

/**
 * Set the viewport width the app's media query resolves against. Call before
 * rendering — the crossover is read in a state initializer — and again after a
 * render to drive a resize; existing lists notify their listeners.
 */
export function setViewportWidth(width: number): void {
  viewportWidth = width;
  if (!installed) {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (media: string) => {
        const list = new FakeMediaQueryList(media);
        lists.add(list);
        return list as unknown as MediaQueryList;
      },
    });
    installed = true;
  }
  for (const list of lists) {
    if (list.evaluate()) list.notify();
  }
}

/** Restore the absent-`matchMedia` default so no test leaks a viewport. */
export function resetViewport(): void {
  viewportWidth = 1024;
  lists.clear();
  if (installed) {
    Reflect.deleteProperty(window, 'matchMedia');
    installed = false;
  }
}
