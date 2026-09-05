import { useCallback, useEffect, useState } from 'react';
import { api, clearKey, getStoredKey, storeKey } from '../lib/api';
import { AuthContext } from './auth-context';

export function AuthProvider({ children }) {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState('');

  const verify = useCallback(async () => {
    if (!getStoredKey()) {
      setAuthed(false);
      setChecking(false);
      return false;
    }
    try {
      await api.get('/auth/check');
      setAuthed(true);
      setChecking(false);
      return true;
    } catch {
      clearKey();
      setAuthed(false);
      setChecking(false);
      return false;
    }
  }, []);

  useEffect(() => {
    verify();
  }, [verify]);

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener('toolgate:unauthorized', onUnauthorized);
    return () => window.removeEventListener('toolgate:unauthorized', onUnauthorized);
  }, []);

  const login = useCallback(async (key) => {
    setError('');
    storeKey(key);
    const ok = await verify();
    if (!ok) setError('Invalid key');
    return ok;
  }, [verify]);

  const logout = useCallback(() => {
    clearKey();
    setAuthed(false);
  }, []);

  return (
    <AuthContext.Provider value={{ authed, checking, error, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
