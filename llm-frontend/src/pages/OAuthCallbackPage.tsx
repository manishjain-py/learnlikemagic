/**
 * OAuthCallbackPage — Handles the redirect after Google OAuth.
 *
 * Uses AuthContext.completeOAuthLogin() to ensure the access token is
 * persisted into AuthContext + api.ts, consistent with all other login paths.
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function OAuthCallbackPage() {
  const navigate = useNavigate();
  const { completeOAuthLogin } = useAuth();
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const complete = async () => {
      try {
        await completeOAuthLogin();
        if (!cancelled) navigate('/');
      } catch {
        if (!cancelled) setError('Failed to complete sign-in. Please try again.');
      }
    };

    // Small delay to let the Cognito SDK process the authorization code
    const timer = setTimeout(complete, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [navigate, completeOAuthLogin]);

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
