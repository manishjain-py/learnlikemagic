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

// Initialize Cognito User Pool
const userPool = new CognitoUserPool({
  UserPoolId: cognitoConfig.UserPoolId,
  ClientId: cognitoConfig.ClientId,
});

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
  sendOTP: (phone: string) => Promise<void>;
  verifyOTP: (code: string) => Promise<void>;
  loginWithGoogle: () => void;
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
        throw new Error('Failed to sync user');
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
    return new Promise<void>((resolve, reject) => {
      const attributeList = [
        new CognitoUserAttribute({ Name: 'email', Value: email }),
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

  const sendOTP = async (phone: string) => {
    return new Promise<void>((resolve, reject) => {
      const cognitoUser = new CognitoUser({
        Username: phone,
        Pool: userPool,
      });

      // Use custom auth flow for phone OTP
      cognitoUser.initiateAuth(
        new AuthenticationDetails({
          Username: phone,
        }),
        {
          onSuccess: () => {
            // Shouldn't happen for OTP flow
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

  const logout = () => {
    const currentUser = userPool.getCurrentUser();
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
    sendOTP,
    verifyOTP,
    loginWithGoogle,
    logout,
    refreshProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
