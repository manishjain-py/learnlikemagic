/**
 * ProfilePage — View and edit profile settings.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const BOARDS = ['CBSE', 'ICSE', 'State Board', 'Other'];

export default function ProfilePage() {
  const navigate = useNavigate();
  const { user, token, logout, refreshProfile } = useAuth();

  const [name, setName] = useState(user?.name || '');
  const [age, setAge] = useState(user?.age?.toString() || '');
  const [grade, setGrade] = useState(user?.grade?.toString() || '');
  const [board, setBoard] = useState(user?.board || '');
  const [schoolName, setSchoolName] = useState(user?.school_name || '');
  const [aboutMe, setAboutMe] = useState(user?.about_me || '');
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');

    try {
      const response = await fetch(`${API_BASE_URL}/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: name.trim() || undefined,
          age: age ? parseInt(age) : undefined,
          grade: grade ? parseInt(grade) : undefined,
          board: board || undefined,
          school_name: schoolName.trim() || undefined,
          about_me: aboutMe.trim() || undefined,
        }),
      });

      if (!response.ok) throw new Error('Failed to update profile');

      await refreshProfile();
      setEditing(false);
      setSuccess('Profile updated!');
    } catch (err: any) {
      setError("Couldn't save changes. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="auth-page">
      <div className="auth-container profile-page">
        <div className="profile-header">
          <button className="auth-back-btn" onClick={() => navigate('/')}>
            ← Back
          </button>
          <h2 className="auth-title">Your Profile</h2>
        </div>

        {error && <div className="auth-error">{error}</div>}
        {success && <div className="auth-success">{success}</div>}

        <form onSubmit={handleSave} className="auth-form">
          <div className="auth-field">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!editing}
            />
          </div>

          <div className="auth-field">
            <label>Age</label>
            <input
              type="number"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              min={5}
              max={18}
              disabled={!editing}
            />
          </div>

          <div className="auth-field">
            <label>Grade</label>
            <select
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
              disabled={!editing}
            >
              <option value="">Select grade</option>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          <div className="auth-field">
            <label>Board</label>
            <select
              value={board}
              onChange={(e) => setBoard(e.target.value)}
              disabled={!editing}
            >
              <option value="">Select board</option>
              {BOARDS.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>

          <div className="auth-field">
            <label>School (optional)</label>
            <input
              type="text"
              value={schoolName}
              onChange={(e) => setSchoolName(e.target.value)}
              placeholder="School name"
              disabled={!editing}
            />
          </div>

          <div className="auth-field">
            <label>About me (optional)</label>
            <textarea
              value={aboutMe}
              onChange={(e) => setAboutMe(e.target.value)}
              placeholder="I like cricket, I learn better with stories..."
              rows={3}
              disabled={!editing}
            />
          </div>

          {editing ? (
            <div className="profile-actions">
              <button type="submit" className="auth-btn auth-btn-primary" disabled={loading}>
                {loading ? 'Saving...' : 'Save Changes'}
              </button>
              <button
                type="button"
                className="auth-btn auth-btn-outline"
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="auth-btn auth-btn-outline"
              onClick={() => setEditing(true)}
            >
              Edit Profile
            </button>
          )}
        </form>

        <div className="profile-section">
          <h3>Account</h3>
          <p className="profile-info">
            Signed in via {user?.auth_provider || 'email'}
            {user?.email && ` (${user.email})`}
            {user?.phone && ` (${user.phone})`}
          </p>
        </div>

        <button className="auth-btn auth-btn-danger" onClick={handleLogout}>
          Log Out
        </button>
      </div>
    </div>
  );
}
