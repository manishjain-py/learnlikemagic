/**
 * OnboardingFlow — Post-signup wizard to collect name, age, grade, board.
 *
 * One question per screen. Each step saves individually via PUT /profile
 * so progress is preserved even if the user closes the app mid-onboarding.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

type Step = 'name' | 'age' | 'grade' | 'board' | 'about' | 'done';

const BOARDS = ['CBSE', 'ICSE', 'State Board', 'Other'];

export default function OnboardingFlow() {
  const navigate = useNavigate();
  const { user, token, refreshProfile } = useAuth();
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState(user?.name || '');
  const [age, setAge] = useState(user?.age?.toString() || '');
  const [grade, setGrade] = useState(user?.grade?.toString() || '');
  const [board, setBoard] = useState(user?.board || '');
  const [aboutMe, setAboutMe] = useState(user?.about_me || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const updateProfile = async (fields: Record<string, any>) => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE_URL}/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(fields),
      });
      if (!response.ok) throw new Error('Failed to save');
      await refreshProfile();
    } catch (err: any) {
      setError("Couldn't save. Let's try again.");
      setLoading(false);
      return false;
    }
    setLoading(false);
    return true;
  };

  const handleNameSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const ok = await updateProfile({ name: name.trim() });
    if (ok) setStep('age');
  };

  const handleAgeSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ageNum = parseInt(age);
    if (isNaN(ageNum) || ageNum < 5 || ageNum > 18) {
      setError('Please enter an age between 5 and 18');
      return;
    }
    const ok = await updateProfile({ age: ageNum });
    if (ok) setStep('grade');
  };

  const handleGradeSubmit = async (gradeNum: number) => {
    const ok = await updateProfile({ grade: gradeNum });
    if (ok) {
      setGrade(gradeNum.toString());
      setStep('board');
    }
  };

  const handleBoardSubmit = async (selectedBoard: string) => {
    const ok = await updateProfile({ board: selectedBoard });
    if (ok) {
      setBoard(selectedBoard);
      setStep('about');
    }
  };

  const handleAboutSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (aboutMe.trim()) {
      await updateProfile({ about_me: aboutMe.trim() });
    }
    setStep('done');
  };

  const handleSkipAbout = async () => {
    setStep('done');
  };

  const handleFinish = () => {
    navigate('/');
  };

  return (
    <div className="auth-page">
      <div className="auth-container onboarding">
        {/* Progress dots */}
        <div className="onboarding-progress">
          {['name', 'age', 'grade', 'board', 'about'].map((s, i) => (
            <div
              key={s}
              className={`onboarding-dot ${
                s === step ? 'active' : ['name', 'age', 'grade', 'board', 'about'].indexOf(step) > i ? 'completed' : ''
              }`}
            />
          ))}
        </div>

        {error && <div className="auth-error">{error}</div>}

        {step === 'name' && (
          <form onSubmit={handleNameSubmit} className="onboarding-step">
            <h2 className="auth-title">What's your name?</h2>
            <div className="auth-field">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                required
                autoFocus
                className="onboarding-input"
              />
            </div>
            <button type="submit" className="auth-btn auth-btn-primary" disabled={loading || !name.trim()}>
              {loading ? 'Saving...' : 'Next'}
            </button>
          </form>
        )}

        {step === 'age' && (
          <form onSubmit={handleAgeSubmit} className="onboarding-step">
            <h2 className="auth-title">How old are you?</h2>
            <div className="auth-field">
              <input
                type="number"
                value={age}
                onChange={(e) => setAge(e.target.value)}
                placeholder="Your age"
                min={5}
                max={18}
                required
                autoFocus
                className="onboarding-input"
              />
            </div>
            <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
              {loading ? 'Saving...' : 'Next'}
            </button>
          </form>
        )}

        {step === 'grade' && (
          <div className="onboarding-step">
            <h2 className="auth-title">What grade are you in?</h2>
            <div className="grade-grid">
              {Array.from({ length: 12 }, (_, i) => i + 1).map((g) => (
                <button
                  key={g}
                  className={`grade-btn ${grade === g.toString() ? 'selected' : ''}`}
                  onClick={() => handleGradeSubmit(g)}
                  disabled={loading}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 'board' && (
          <div className="onboarding-step">
            <h2 className="auth-title">What's your school board?</h2>
            <div className="board-list">
              {BOARDS.map((b) => (
                <button
                  key={b}
                  className={`auth-btn auth-btn-outline ${board === b ? 'selected' : ''}`}
                  onClick={() => handleBoardSubmit(b)}
                  disabled={loading}
                >
                  {b}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 'about' && (
          <form onSubmit={handleAboutSubmit} className="onboarding-step">
            <h2 className="auth-title">Tell us about yourself!</h2>
            <p className="auth-subtitle">
              What do you like? How do you learn best? This is optional.
            </p>
            <div className="auth-field">
              <textarea
                value={aboutMe}
                onChange={(e) => setAboutMe(e.target.value)}
                placeholder="I like cricket, I learn better with stories..."
                rows={4}
                autoFocus
                className="onboarding-textarea"
              />
            </div>
            <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
              {loading ? 'Saving...' : aboutMe.trim() ? 'Save & Continue' : 'Continue'}
            </button>
            <button type="button" className="auth-link skip-btn" onClick={handleSkipAbout}>
              Skip for now
            </button>
          </form>
        )}

        {step === 'done' && (
          <div className="onboarding-step done-step">
            <h2 className="auth-title">You're all set{name ? `, ${name}` : ''}!</h2>
            <p className="auth-subtitle">Let's start learning.</p>
            <button className="auth-btn auth-btn-primary" onClick={handleFinish}>
              Start Learning
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
