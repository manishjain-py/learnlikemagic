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
    <div className="auth-page chalkboard-active">
      <div className="auth-container">
        <div className="auth-logo">
          <svg className="auth-logo-icon" width="48" height="48" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="authLogoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#667eea"/>
                <stop offset="100%" stopColor="#764ba2"/>
              </linearGradient>
            </defs>
            {/* Open book */}
            <path d="M8 44 C8 40, 16 36, 32 38 C48 36, 56 40, 56 44 L56 52 C56 50, 48 48, 32 50 C16 48, 8 50, 8 52 Z" fill="url(#authLogoGrad)" opacity="0.85"/>
            <line x1="32" y1="38" x2="32" y2="50" stroke="white" strokeWidth="1.2" opacity="0.6"/>
            {/* Wand */}
            <line x1="32" y1="36" x2="32" y2="16" stroke="url(#authLogoGrad)" strokeWidth="2.5" strokeLinecap="round"/>
            {/* Star at wand tip */}
            <polygon points="32,8 34,14 40,14 35,18 37,24 32,20 27,24 29,18 24,14 30,14" fill="url(#authLogoGrad)"/>
            {/* Sparkles */}
            <circle cx="20" cy="16" r="1.8" fill="#667eea" opacity="0.7"/>
            <circle cx="44" cy="12" r="1.5" fill="#764ba2" opacity="0.6"/>
            <circle cx="46" cy="24" r="1.2" fill="#667eea" opacity="0.5"/>
            <circle cx="18" cy="26" r="1.3" fill="#764ba2" opacity="0.5"/>
            {/* Sparkle crosses */}
            <g stroke="#667eea" strokeWidth="1.2" opacity="0.7">
              <line x1="22" y1="22" x2="22" y2="26"/>
              <line x1="20" y1="24" x2="24" y2="24"/>
            </g>
            <g stroke="#764ba2" strokeWidth="1.2" opacity="0.6">
              <line x1="42" y1="18" x2="42" y2="22"/>
              <line x1="40" y1="20" x2="44" y2="20"/>
            </g>
          </svg>
          <h1>Learn Like Magic</h1>
          <p className="auth-tagline">Your personal tutor, always ready to help</p>
        </div>

        <div className="auth-buttons">
          <button
            className="auth-btn auth-btn-phone"
            disabled
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
          >
            Continue with Phone (coming soon)
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
