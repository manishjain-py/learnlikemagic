/**
 * AuthContext — global auth state for the app.
 *
 * Provides:
 * - user: current user profile (or null)
 * - isAuthenticated: boolean
 * - isLoading: boolean (true during initial token check)
 * - login/signup/logout functions
 * - token: current access JWT for API calls
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
  CognitoUserAttribute,
} from 'amazon-cognito-identity-js';
import { cognitoConfig } from '../config/auth';
import { setAccessToken } from '../api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Initialize Cognito User Pool (may be null if credentials not configured)
const isCognitoConfigured = !!(cognitoConfig.UserPoolId && cognitoConfig.ClientId);
const userPool = isCognitoConfigured
  ? new CognitoUserPool({
      UserPoolId: cognitoConfig.UserPoolId,
      ClientId: cognitoConfig.ClientId,
    })
  : null;

export interface UserProfile {
  id: string;
  email?: string;
  phone?: string;
  name?: string;
  age?: number;
  grade?: number;
  board?: string;
  school_name?: string;
  about_me?: string;
  onboarding_complete: boolean;
  auth_provider: string;
}

interface AuthContextType {
  user: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  needsOnboarding: boolean;
  loginWithEmail: (email: string, password: string) => Promise<void>;
  signupWithEmail: (email: string, password: string) => Promise<void>;
  confirmSignUp: (email: string, code: string) => Promise<void>;
  resendConfirmationCode: (email: string) => Promise<void>;
  sendOTP: (phone: string) => Promise<void>;
  verifyOTP: (code: string) => Promise<void>;
  loginWithGoogle: () => void;
  completeOAuthLogin: () => Promise<void>;
  logout: () => void;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// Store for OTP flow (phone login requires intermediate state)
let pendingCognitoUser: CognitoUser | null = null;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = !!user && !!token;
  const needsOnboarding = !!user && !user.onboarding_complete;

  // Sync user profile with backend after Cognito auth
  const syncUser = useCallback(async (idToken: string, accessToken: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${idToken}`,
        },
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`Failed to sync user: ${response.status} ${body}`);
      }
      const profile: UserProfile = await response.json();
      setUser(profile);
      setToken(accessToken);
      setAccessToken(accessToken); // Sync with api.ts module
    } catch (error) {
      console.error('Failed to sync user with backend:', error);
      throw error;
    }
  }, []);

  // Check for existing session on mount
  useEffect(() => {
    if (!userPool) {
      setIsLoading(false);
      return;
    }
    const currentUser = userPool.getCurrentUser();
    if (currentUser) {
      currentUser.getSession(async (err: Error | null, session: CognitoUserSession | null) => {
        if (err || !session || !session.isValid()) {
          setIsLoading(false);
          return;
        }
        try {
          const idToken = session.getIdToken().getJwtToken();
          const accessToken = session.getAccessToken().getJwtToken();
          await syncUser(idToken, accessToken);
        } catch {
          // Session expired or invalid
        }
        setIsLoading(false);
      });
    } else {
      setIsLoading(false);
    }
  }, [syncUser]);

  const loginWithEmail = async (email: string, password: string) => {
    if (!userPool) throw new Error('Authentication is not configured. Please set Cognito credentials.');
    return new Promise<void>((resolve, reject) => {
      const cognitoUser = new CognitoUser({
        Username: email,
        Pool: userPool,
      });

      const authDetails = new AuthenticationDetails({
        Username: email,
        Password: password,
      });

      cognitoUser.authenticateUser(authDetails, {
        onSuccess: async (session: CognitoUserSession) => {
          try {
            const idToken = session.getIdToken().getJwtToken();
            const accessToken = session.getAccessToken().getJwtToken();
            await syncUser(idToken, accessToken);
            resolve();
          } catch (error) {
            reject(error);
          }
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  };

  const signupWithEmail = async (email: string, password: string) => {
    if (!userPool) throw new Error('Authentication is not configured. Please set Cognito credentials.');
    return new Promise<void>((resolve, reject) => {
      const attributeList = [
        new CognitoUserAttribute({ Name: 'email', Value: email }),
        new CognitoUserAttribute({ Name: 'name', Value: email.split('@')[0] }),
      ];

      userPool.signUp(email, password, attributeList, [], (err, result) => {
        if (err) {
          reject(err);
          return;
        }
        // After signup, user needs to verify email before logging in
        // For now, we'll auto-login after signup (Cognito handles verification)
        resolve();
      });
    });
  };

  const confirmSignUp = async (email: string, code: string) => {
    if (!userPool) throw new Error('Authentication is not configured.');
    return new Promise<void>((resolve, reject) => {
      const cognitoUser = new CognitoUser({ Username: email, Pool: userPool });
      cognitoUser.confirmRegistration(code, true, (err) => {
        if (err) {
          reject(err);
          return;
        }
        resolve();
      });
    });
  };

  const resendConfirmationCode = async (email: string) => {
    if (!userPool) throw new Error('Authentication is not configured.');
    return new Promise<void>((resolve, reject) => {
      const cognitoUser = new CognitoUser({ Username: email, Pool: userPool });
      cognitoUser.resendConfirmationCode((err) => {
        if (err) {
          reject(err);
          return;
        }
        resolve();
      });
    });
  };

  const sendOTP = async (phone: string) => {
    if (!userPool) throw new Error('Authentication is not configured. Please set Cognito credentials.');

    // Ensure user exists in Cognito via backend admin API
    // (client-side signUp can't work because email/name are required schema attributes)
    const provisionRes = await fetch(`${API_BASE_URL}/auth/phone/provision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone }),
    });
    if (!provisionRes.ok) {
      const err = await provisionRes.text();
      throw new Error(`Failed to provision phone user: ${err}`);
    }

    // Now initiate custom auth (OTP) flow
    return new Promise<void>((resolve, reject) => {
      const cognitoUser = new CognitoUser({
        Username: phone,
        Pool: userPool,
      });

      cognitoUser.initiateAuth(
        new AuthenticationDetails({
          Username: phone,
        }),
        {
          onSuccess: () => {
            resolve();
          },
          onFailure: (err: Error) => {
            reject(err);
          },
          customChallenge: () => {
            pendingCognitoUser = cognitoUser;
            resolve();
          },
        }
      );
    });
  };

  const verifyOTP = async (code: string) => {
    return new Promise<void>((resolve, reject) => {
      if (!pendingCognitoUser) {
        reject(new Error('No pending OTP verification. Call sendOTP first.'));
        return;
      }

      pendingCognitoUser.sendCustomChallengeAnswer(code, {
        onSuccess: async (session: CognitoUserSession) => {
          try {
            const idToken = session.getIdToken().getJwtToken();
            const accessToken = session.getAccessToken().getJwtToken();
            await syncUser(idToken, accessToken);
            pendingCognitoUser = null;
            resolve();
          } catch (error) {
            reject(error);
          }
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  };

  const loginWithGoogle = () => {
    // Redirect to Cognito hosted UI for Google OAuth
    const domain = cognitoConfig.Domain;
    const clientId = cognitoConfig.ClientId;
    const redirectUri = `${window.location.origin}/auth/callback`;
    const url = `https://${domain}.auth.${cognitoConfig.Region}.amazoncognito.com/oauth2/authorize?response_type=code&client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&identity_provider=Google&scope=openid+email+profile`;
    window.location.href = url;
  };

  const completeOAuthLogin = async () => {
    // Called by OAuthCallbackPage after Cognito redirect.
    // Cognito redirects with ?code=xxx which we exchange for tokens
    // via the /oauth2/token endpoint, then sync with our backend.
    if (!userPool) throw new Error('Authentication is not configured. Please set Cognito credentials.');

    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    if (!code) throw new Error('No authorization code in redirect URL');

    const domain = cognitoConfig.Domain;
    const region = cognitoConfig.Region;
    const clientId = cognitoConfig.ClientId;
    const redirectUri = `${window.location.origin}/auth/callback`;
    const tokenUrl = `https://${domain}.auth.${region}.amazoncognito.com/oauth2/token`;

    const response = await fetch(tokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId,
        redirect_uri: redirectUri,
        code,
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Token exchange failed: ${err}`);
    }

    const tokens = await response.json();
    await syncUser(tokens.id_token, tokens.access_token);

    // Store tokens in Cognito SDK storage so getCurrentUser() works for session restore
    const idTokenPayload = JSON.parse(atob(tokens.id_token.split('.')[1]));
    const username = idTokenPayload['cognito:username'] || idTokenPayload.sub;
    const keyPrefix = `CognitoIdentityServiceProvider.${clientId}`;
    const storage = window.localStorage;
    storage.setItem(`${keyPrefix}.${username}.idToken`, tokens.id_token);
    storage.setItem(`${keyPrefix}.${username}.accessToken`, tokens.access_token);
    storage.setItem(`${keyPrefix}.${username}.refreshToken`, tokens.refresh_token);
    storage.setItem(`${keyPrefix}.LastAuthUser`, username);
  };

  const logout = () => {
    const currentUser = userPool?.getCurrentUser();
    if (currentUser) {
      currentUser.signOut();
    }
    setUser(null);
    setToken(null);
    setAccessToken(null); // Clear api.ts module token
  };

  const refreshProfile = async () => {
    if (!token) return;
    try {
      const response = await fetch(`${API_BASE_URL}/profile`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (response.ok) {
        const profile: UserProfile = await response.json();
        setUser(profile);
      }
    } catch (error) {
      console.error('Failed to refresh profile:', error);
    }
  };

  const value: AuthContextType = {
    user,
    token,
    isAuthenticated,
    isLoading,
    needsOnboarding,
    loginWithEmail,
    signupWithEmail,
    confirmSignUp,
    resendConfirmationCode,
    sendOTP,
    verifyOTP,
    loginWithGoogle,
    completeOAuthLogin,
    logout,
    refreshProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
