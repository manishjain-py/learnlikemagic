/**
 * EmailVerifyPage — 6-digit code input to confirm email after signup.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function EmailVerifyPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { confirmSignUp, resendConfirmationCode, loginWithEmail } = useAuth();

  const state = location.state as { email?: string; password?: string } | null;
  const email = state?.email || '';
  const password = state?.password || '';

  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(30);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (resendCooldown > 0) {
      const timer = setTimeout(() => setResendCooldown(resendCooldown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [resendCooldown]);

  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  if (!email) {
    navigate('/signup/email');
    return null;
  }

  const handleChange = async (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;

    const newOtp = [...otp];
    newOtp[index] = value.slice(-1);
    setOtp(newOtp);

    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    const fullCode = newOtp.join('');
    if (fullCode.length === 6) {
      setLoading(true);
      setError('');
      try {
        await confirmSignUp(email, fullCode);
        // Auto-login after verification
        if (password) {
          await loginWithEmail(email, password);
        }
        navigate('/');
      } catch (err: any) {
        setError(err.message || "That code didn't work. Let's try again.");
        setOtp(['', '', '', '', '', '']);
        inputRefs.current[0]?.focus();
      } finally {
        setLoading(false);
      }
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handleResend = async () => {
    if (resendCooldown > 0) return;
    try {
      await resendConfirmationCode(email);
      setResendCooldown(30);
      setError('');
    } catch (err: any) {
      setError('Failed to resend code.');
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-container">
        <button className="auth-back-btn" onClick={() => navigate('/signup/email')}>
          &larr; Back
        </button>

        <h2 className="auth-title">Check your email</h2>
        <p className="auth-subtitle">We sent a 6-digit code to {email}</p>

        {error && <div className="auth-error">{error}</div>}

        <div className="otp-container">
          {otp.map((digit, index) => (
            <input
              key={index}
              ref={(el) => { inputRefs.current[index] = el; }}
              type="text"
              inputMode="numeric"
              maxLength={1}
              value={digit}
              onChange={(e) => handleChange(index, e.target.value)}
              onKeyDown={(e) => handleKeyDown(index, e)}
              className="otp-input"
              disabled={loading}
            />
          ))}
        </div>

        {loading && <p className="auth-subtitle">Verifying...</p>}

        <button
          className="auth-link"
          onClick={handleResend}
          disabled={resendCooldown > 0}
          style={{ marginTop: '16px' }}
        >
          {resendCooldown > 0 ? `Resend code in ${resendCooldown}s` : 'Resend code'}
        </button>
      </div>
    </div>
  );
}
