/**
 * Minimal client-side router built on the History API.
 *
 * CloudFront serves index.html for unknown paths, so deep links work.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RouterContext, useRouter } from './routing';

function currentLocation() {
  return { pathname: window.location.pathname, search: window.location.search };
}

/**
 * Provides the current location and a navigate() function.
 *
 * @param {{children: React.ReactNode}} props
 */
export function RouterProvider({ children }) {
  const [location, setLocation] = useState(currentLocation);

  useEffect(() => {
    const onPop = () => setLocation(currentLocation());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const navigate = useCallback((to, { replace = false } = {}) => {
    if (replace) window.history.replaceState({}, '', to);
    else window.history.pushState({}, '', to);
    setLocation(currentLocation());
    window.scrollTo?.(0, 0);
  }, []);

  const value = useMemo(() => ({
    path: location.pathname,
    query: Object.fromEntries(new URLSearchParams(location.search)),
    navigate,
  }), [location, navigate]);

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

/**
 * An anchor that navigates without a page reload.
 *
 * @param {{to: string, children: React.ReactNode, onClick?: Function}} props
 */
export function Link({ to, children, onClick, ...rest }) {
  const { navigate } = useRouter();
  const handleClick = (event) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={handleClick} {...rest}>{children}</a>;
}
