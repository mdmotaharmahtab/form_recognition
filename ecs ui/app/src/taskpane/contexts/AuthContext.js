import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { message } from "antd";
import { loginRequest, msalInstance } from "../../authConfig";

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const initAuth = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await msalInstance.initialize();

      let account;
      const currentAccounts = msalInstance.getAllAccounts();
      if (currentAccounts.length > 0) {
        account = currentAccounts[0];
        msalInstance.setActiveAccount(account);
        setUser(account);
      } else {
        const loginResponse = await msalInstance.loginPopup(loginRequest);
        account = loginResponse.account;
        msalInstance.setActiveAccount(account);
        setUser(account);
      }

      try {
        const tokenResponse = await msalInstance.acquireTokenSilent({
          ...loginRequest,
          account,
        });
        setToken(tokenResponse.accessToken);
      } catch {
        const tokenResponse = await msalInstance.acquireTokenPopup(loginRequest);
        setToken(tokenResponse.accessToken);
      }
    } catch (err) {
      setError(err.message || "Login failed");
      message.error(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Run on mount
  useEffect(() => {
    initAuth();
  }, [initAuth]);

  const logout = () => {
    msalInstance.logoutPopup().then(() => {
      setUser(null);
      setToken(null);
    });
  };

  return (
    <AuthContext.Provider value={{ user, setUser, token, setToken, loading, error, login: initAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
