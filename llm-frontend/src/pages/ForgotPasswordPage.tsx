/**
 * ForgotPasswordPage — Password reset flow.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CognitoUser } from 'amazon-cognito-identity-js';
import { cognitoConfig } from '../config/auth';
import { CognitoUserPool } from 'amazon-cognito-identity-js';

const userPool = new CognitoUserPool({
  UserPoolId: cognitoConfig.UserPoolId,
  ClientId: cognitoConfig.ClientId,
});

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool });

    cognitoUser.forgotPassword({
      onSuccess: () => {
        setStep('code');
        setLoading(false);
      },
      onFailure: (err: Error) => {
        setError(err.message || 'Failed to send reset code.');
        setLoading(false);
      },
    });
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool });

    cognitoUser.confirmPassword(code, newPassword, {
      onSuccess: () => {
        setSuccess(true);
        setLoading(false);
      },
      onFailure: (err: Error) => {
        setError(err.message || 'Failed to reset password.');
        setLoading(false);
      },
    });
  };

  if (success) {
    return (
      <div className="auth-page">
        <div className="auth-container">
          <h2 className="auth-title">Password reset!</h2>
          <p className="auth-subtitle">You can now log in with your new password.</p>
          <button
            className="auth-btn auth-btn-primary"
            onClick={() => navigate('/login/email')}
          >
            Go to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <button className="auth-back-btn" onClick={() => navigate('/login/email')}>
          ← Back
        </button>

        {step === 'email' ? (
          <>
            <h2 className="auth-title">Forgot your password?</h2>
            <p className="auth-subtitle">Enter your email and we'll send a reset code</p>

            {error && <div className="auth-error">{error}</div>}

            <form onSubmit={handleSendCode} className="auth-form">
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

              <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
                {loading ? 'Sending...' : 'Send Reset Code'}
              </button>
            </form>
          </>
        ) : (
          <>
            <h2 className="auth-title">Check your email</h2>
            <p className="auth-subtitle">Enter the code we sent to {email}</p>

            {error && <div className="auth-error">{error}</div>}

            <form onSubmit={handleResetPassword} className="auth-form">
              <div className="auth-field">
                <label htmlFor="code">Reset Code</label>
                <input
                  id="code"
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="6-digit code"
                  required
                  autoFocus
                />
              </div>

              <div className="auth-field">
                <label htmlFor="newPassword">New Password</label>
                <input
                  id="newPassword"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  required
                  minLength={8}
                />
              </div>

              <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
                {loading ? 'Resetting...' : 'Reset Password'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
