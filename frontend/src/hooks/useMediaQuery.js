import { useSyncExternalStore } from 'react';

/**
 * Track a CSS media query (layout itself is done with CSS; this is for JS-only decisions).
 *
 * @param {string} query e.g. '(max-width: 800px)'
 * @returns {boolean} Whether the query currently matches
 */
export function useMediaQuery(query) {
  return useSyncExternalStore(
    (onChange) => {
      if (!window.matchMedia) return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    () => (window.matchMedia ? window.matchMedia(query).matches : false),
    () => false,
  );
}
