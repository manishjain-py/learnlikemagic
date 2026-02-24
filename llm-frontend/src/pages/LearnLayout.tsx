import React, { useState, useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useStudentProfile } from '../hooks/useStudentProfile';
import { getModelConfig } from '../api';
import '../App.css';

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '10px 16px',
  border: 'none',
  background: 'none',
  textAlign: 'left' as const,
  fontSize: '0.9rem',
  cursor: 'pointer',
  color: '#333',
};

export default function LearnLayout() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { board, grade, country } = useStudentProfile();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [modelLabel, setModelLabel] = useState('');

  useEffect(() => {
    getModelConfig()
      .then((config) => setModelLabel(config.tutor?.description || config.tutor?.model_id || ''))
      .catch(() => setModelLabel(''));
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app">
      <header className="header" style={{ position: 'relative' }}>
        <h1>{user?.name ? `Hi, ${user.name}!` : 'Learn Like Magic'}</h1>
        <p className="subtitle">
          {board} &bull; Grade {grade} &bull; {country}
        </p>
        <div style={{ position: 'absolute', top: '12px', right: '12px' }}>
          <button
            onClick={() => setShowUserMenu(!showUserMenu)}
            style={{
              padding: '6px 12px',
              background: 'rgba(255,255,255,0.2)',
              color: 'white',
              border: '1px solid rgba(255,255,255,0.4)',
              borderRadius: '20px',
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            {user?.name || 'Menu'}
          </button>
          {showUserMenu && (
            <div style={{
              position: 'absolute',
              top: '40px',
              right: 0,
              background: 'white',
              borderRadius: '8px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
              minWidth: '160px',
              zIndex: 100,
              overflow: 'hidden',
            }}>
              <button onClick={() => { setShowUserMenu(false); navigate('/profile'); }}
                style={menuItemStyle}>Profile</button>
              <button onClick={() => { setShowUserMenu(false); navigate('/history'); }}
                style={menuItemStyle}>My Sessions</button>
              <button onClick={() => { setShowUserMenu(false); navigate('/scorecard'); }}
                style={menuItemStyle}>My Scorecard</button>
              <button onClick={handleLogout}
                style={{ ...menuItemStyle, color: '#e53e3e' }}>Log Out</button>
            </div>
          )}
        </div>
      </header>

      <div className="selection-container">
        <Outlet context={{ modelLabel }} />
      </div>
    </div>
  );
}
