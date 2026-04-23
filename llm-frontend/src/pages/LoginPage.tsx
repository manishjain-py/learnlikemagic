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
          <svg className="auth-logo-icon" width="72" height="72" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            {/* Open book — chalk outline */}
            <path d="M10 22 L40 18 L70 22 L70 60 L40 56 L10 60 Z" stroke="#F4F4EF" strokeWidth="2" fill="none" strokeLinejoin="round"/>
            <path d="M40 18 L40 56" stroke="#F4F4EF" strokeWidth="2"/>
            <path d="M16 30 L34 27 M16 36 L34 33 M16 42 L34 39" stroke="#F4F4EF" strokeWidth="1.2" strokeLinecap="round"/>
            <path d="M46 27 L64 30 M46 33 L64 36 M46 39 L64 42" stroke="#F4F4EF" strokeWidth="1.2" strokeLinecap="round"/>
            {/* Wand — gold chalk */}
            <line x1="55" y1="10" x2="30" y2="38" stroke="#F4C76C" strokeWidth="3" strokeLinecap="round"/>
            {/* Star — gold chalk */}
            <path d="M58 6 L61 12 L67 13 L62.5 17 L64 23 L58 20 L52 23 L53.5 17 L49 13 L55 12 Z" fill="#F4C76C"/>
            {/* Chalk sparkles */}
            <circle cx="22" cy="14" r="1.5" fill="#F4F4EF"/>
            <circle cx="68" cy="52" r="1.5" fill="#F4F4EF"/>
            <circle cx="14" cy="48" r="1" fill="#F4F4EF"/>
          </svg>
          <h1>Learn Like Magic</h1>
          <p className="auth-tagline">Your personal tutor, always ready to help</p>
        </div>

        <div className="auth-buttons">
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

          <button
            className="auth-btn auth-btn-phone"
            disabled
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
          >
            Continue with Phone (coming soon)
          </button>
        </div>

        <p className="auth-footer">
          By continuing, you agree to our Terms of Service
        </p>
      </div>
    </div>
  );
}
