/**
 * LoginPage — Welcome screen with auth method buttons.
 * "One thing per screen" — just shows the three auth options.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function LoginPage() {
  const navigate = useNavigate();
  const { loginWithGoogle } = useAuth();

  return (
    <div className="auth-page">
      <div className="auth-container">
        <div className="auth-logo">
          <h1>Learn Like Magic</h1>
          <p className="auth-tagline">Your personal tutor, always ready to help</p>
        </div>

        <div className="auth-buttons">
          <button
            className="auth-btn auth-btn-phone"
            onClick={() => navigate('/login/phone')}
          >
            Continue with Phone
          </button>

          <button
            className="auth-btn auth-btn-email"
            onClick={() => navigate('/login/email')}
          >
            Continue with Email
          </button>

          <button
            className="auth-btn auth-btn-google"
            onClick={loginWithGoogle}
          >
            Continue with Google
          </button>
        </div>

        <p className="auth-footer">
          By continuing, you agree to our Terms of Service
        </p>
      </div>
    </div>
  );
}
