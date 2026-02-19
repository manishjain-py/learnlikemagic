/**
 * PhoneLoginPage — Phone number input + country code selector.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function PhoneLoginPage() {
  const navigate = useNavigate();
  const { sendOTP } = useAuth();
  const [countryCode, setCountryCode] = useState('+91');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Strip spaces and dashes
    const cleanPhone = phone.replace(/[\s-]/g, '');
    const fullPhone = `${countryCode}${cleanPhone}`;

    if (cleanPhone.length < 10) {
      setError('Please enter a valid phone number');
      return;
    }

    setLoading(true);

    try {
      await sendOTP(fullPhone);
      navigate('/login/phone/verify', { state: { phone: fullPhone } });
    } catch (err: any) {
      setError(err.message || "Couldn't send OTP. Please try again.");
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

        <h2 className="auth-title">What's your phone number?</h2>
        <p className="auth-subtitle">We'll send you a code to verify</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label htmlFor="phone">Phone Number</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <select
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value)}
                style={{ width: '100px', padding: '12px 8px', borderRadius: '8px', border: '1px solid #ddd', fontSize: '1rem' }}
              >
                <option value="+91">+91 IN</option>
                <option value="+1">+1 US</option>
                <option value="+44">+44 UK</option>
                <option value="+61">+61 AU</option>
              </select>
              <input
                id="phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="Phone number"
                required
                autoFocus
                style={{ flex: 1 }}
              />
            </div>
          </div>

          <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
            {loading ? 'Sending code...' : 'Send OTP'}
          </button>
        </form>
      </div>
    </div>
  );
}
