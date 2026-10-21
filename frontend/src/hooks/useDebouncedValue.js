import { useEffect, useState } from 'react';

/**
 * Return `value` after it has stopped changing for `delay` ms (for search boxes).
 *
 * @param {any} value
 * @param {number} [delay]
 */
export function useDebouncedValue(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
