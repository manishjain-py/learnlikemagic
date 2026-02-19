/**
 * EmailSignupPage — Email + password signup form.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const passwordRules = [
  { test: (p: string) => p.length >= 8, label: 'At least 8 characters' },
  { test: (p: string) => /[a-z]/.test(p), label: 'One lowercase letter' },
  { test: (p: string) => /[A-Z]/.test(p), label: 'One uppercase letter' },
  { test: (p: string) => /[0-9]/.test(p), label: 'One number' },
];

export default function EmailSignupPage() {
  const navigate = useNavigate();
  const { signupWithEmail } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const allRulesPassed = passwordRules.every((r) => r.test(password));
  const passwordsMatch = password === confirmPassword;
  const formValid = email && allRulesPassed && confirmPassword && passwordsMatch;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!allRulesPassed || !passwordsMatch) return;

    setLoading(true);

    try {
      await signupWithEmail(email, password);
      navigate('/signup/email/verify', { state: { email, password } });
    } catch (err: any) {
      setError(err.message || "Hmm, that didn't work. Let's try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-container">
        <button className="auth-back-btn" onClick={() => navigate('/login')}>
          &larr; Back
        </button>

        <h2 className="auth-title">Create your account</h2>
        <p className="auth-subtitle">Let's get you started</p>

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
              placeholder="Create a password"
              required
            />
            {password.length > 0 && (
              <ul className="password-rules">
                {passwordRules.map((rule) => {
                  const passed = rule.test(password);
                  return (
                    <li key={rule.label} className={passed ? 'rule-pass' : 'rule-fail'}>
                      <span className="rule-icon">{passed ? '\u2713' : '\u2022'}</span>
                      {rule.label}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="auth-field">
            <label htmlFor="confirmPassword">Confirm Password</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Type it again"
              required
            />
            {confirmPassword.length > 0 && !passwordsMatch && (
              <span className="password-mismatch">Passwords don't match</span>
            )}
          </div>

          <button
            type="submit"
            className="auth-btn auth-btn-primary"
            disabled={loading || !formValid}
          >
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <div className="auth-links">
          <button className="auth-link" onClick={() => navigate('/login/email')}>
            Already have an account? Log in
          </button>
        </div>
      </div>
    </div>
  );
}
