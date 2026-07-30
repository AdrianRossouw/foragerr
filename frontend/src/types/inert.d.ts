import 'react';

/**
 * `inert` is a standard HTML attribute (focus + assistive-technology exclusion
 * for a whole subtree) that React 18's JSX attribute types predate. It is
 * boolean-by-presence in the DOM, so the empty string sets it and `undefined`
 * removes it; typing it as `''` keeps a truthy-boolean from being passed, which
 * React 18 would reject as a non-boolean attribute value.
 */
declare module 'react' {
  interface HTMLAttributes<T> {
    inert?: '' | undefined;
  }
}
