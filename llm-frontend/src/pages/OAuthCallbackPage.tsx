/**
 * OAuthCallbackPage — Handles the redirect after Google OAuth.
 * Cognito redirects here with an authorization code, which the SDK exchanges for tokens.
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CognitoUserPool } from 'amazon-cognito-identity-js';
import { cognitoConfig } from '../config/auth';
import { useAuth } from '../contexts/AuthContext';

const userPool = new CognitoUserPool({
  UserPoolId: cognitoConfig.UserPoolId,
  ClientId: cognitoConfig.ClientId,
});

export default function OAuthCallbackPage() {
  const navigate = useNavigate();
  const { refreshProfile } = useAuth();
  const [error, setError] = useState('');

  useEffect(() => {
    // The Cognito SDK handles token exchange automatically when using hosted UI.
    // After redirect, check if session is now available.
    const currentUser = userPool.getCurrentUser();
    if (currentUser) {
      currentUser.getSession(async (err: Error | null, session: any) => {
        if (err || !session || !session.isValid()) {
          setError('Authentication failed. Please try again.');
          return;
        }
        // Sync user profile with backend
        try {
          const idToken = session.getIdToken().getJwtToken();
          const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
          await fetch(`${API_BASE_URL}/auth/sync`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${idToken}`,
            },
          });
          await refreshProfile();
          navigate('/');
        } catch {
          setError('Failed to complete sign-in. Please try again.');
        }
      });
    } else {
      // No session yet — might still be processing
      setTimeout(() => {
        const user = userPool.getCurrentUser();
        if (!user) {
          setError('Authentication failed. Please try again.');
        }
      }, 3000);
    }
  }, [navigate, refreshProfile]);

  if (error) {
    return (
      <div className="auth-page">
        <div className="auth-container">
          <h2 className="auth-title">Oops!</h2>
          <p className="auth-subtitle">{error}</p>
          <button className="auth-btn auth-btn-primary" onClick={() => navigate('/login')}>
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <h2 className="auth-title">Signing you in...</h2>
        <p className="auth-subtitle">Just a moment</p>
      </div>
    </div>
  );
}
