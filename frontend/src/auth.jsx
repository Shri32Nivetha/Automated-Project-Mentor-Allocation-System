import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!getToken());
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    if (!getToken()) return;
    api("/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const h = () => { setUser(null); setExpired(true); };
    window.addEventListener("pga-session-expired", h);
    return () => window.removeEventListener("pga-session-expired", h);
  }, []);

  const login = useCallback(async (email, password) => {
    const d = await api("/auth/login", { method: "POST", body: { email, password } });
    setToken(d.access_token);
    setUser(d.user);
    setExpired(false);
    return d.user;
  }, []);
  const logout = useCallback(() => { setToken(null); setUser(null); }, []);
  return <Ctx.Provider value={{ user, loading, login, logout, expired, setExpired }}>{children}</Ctx.Provider>;
}
