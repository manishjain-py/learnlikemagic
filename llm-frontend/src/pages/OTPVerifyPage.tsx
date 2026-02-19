/**
 * OTPVerifyPage — 6-digit OTP input with auto-submit on fill.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function OTPVerifyPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { verifyOTP, sendOTP } = useAuth();
  const phone = (location.state as any)?.phone || '';

  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(30);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown > 0) {
      const timer = setTimeout(() => setResendCooldown(resendCooldown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [resendCooldown]);

  // Focus first input on mount
  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  const handleChange = async (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return; // Only digits

    const newOtp = [...otp];
    newOtp[index] = value.slice(-1); // Take last digit
    setOtp(newOtp);

    // Auto-advance to next field
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all 6 digits are filled
    const fullCode = newOtp.join('');
    if (fullCode.length === 6) {
      setLoading(true);
      setError('');
      try {
        await verifyOTP(fullCode);
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
      await sendOTP(phone);
      setResendCooldown(30);
      setError('');
    } catch (err: any) {
      setError('Failed to resend code.');
    }
  };

  if (!phone) {
    navigate('/login/phone');
    return null;
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <button className="auth-back-btn" onClick={() => navigate('/login/phone')}>
          ← Back
        </button>

        <h2 className="auth-title">Enter the code</h2>
        <p className="auth-subtitle">We sent a 6-digit code to {phone}</p>

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
