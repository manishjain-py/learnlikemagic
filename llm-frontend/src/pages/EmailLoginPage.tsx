/**
 * EmailLoginPage — Email + password login form.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function EmailLoginPage() {
  const navigate = useNavigate();
  const { loginWithEmail } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await loginWithEmail(email, password);
      navigate('/');
    } catch (err: any) {
      setError(err.message || "Hmm, that didn't work. Check your email and password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-container">
        <button className="auth-back-btn" onClick={() => navigate('/login')}>
          ← Back
        </button>

        <h2 className="auth-title">Welcome back!</h2>
        <p className="auth-subtitle">Log in with your email</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              required
              autoFocus
            />
          </div>

          <div className="auth-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password"
              required
              minLength={8}
            />
          </div>

          <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
            {loading ? 'Logging in...' : 'Log In'}
          </button>
        </form>

        <div className="auth-links">
          <button className="auth-link" onClick={() => navigate('/forgot-password')}>
            Forgot password?
          </button>
          <button className="auth-link" onClick={() => navigate('/signup/email')}>
            Don't have an account? Sign up
          </button>
        </div>
      </div>
    </div>
  );
}
