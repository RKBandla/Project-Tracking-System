import { useCallback, useEffect, useState } from 'react';

/**
 * Run an async loader whenever `key` changes and expose its state.
 *
 * @param {() => Promise<any>} loader Function returning a promise
 * @param {string} key Serialisable key; a new key triggers a reload
 * @returns {{data: any, error: Error|null, loading: boolean, reload: Function, setData: Function}}
 */
export function useAsync(loader, key) {
  const [version, setVersion] = useState(0);
  const requestKey = `${key}#${version}`;
  const [state, setState] = useState({ key: null, data: null, error: null });

  useEffect(() => {
    let active = true;
    loader().then(
      (data) => { if (active) setState({ key: requestKey, data, error: null }); },
      (error) => { if (active) setState((prev) => ({ key: requestKey, data: prev.data, error })); },
    );
    return () => { active = false; };
    // the loader is re-created every render; requestKey captures what it depends on
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const setData = useCallback((data) => setState((prev) => ({ ...prev, data })), []);

  return {
    data: state.data,
    error: state.key === requestKey ? state.error : null,
    loading: state.key !== requestKey,
    reload,
    setData,
  };
}
