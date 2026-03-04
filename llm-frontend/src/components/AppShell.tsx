import React, { useState, useEffect, useRef } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import '../App.css';

export default function AppShell() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!showUserMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showUserMenu]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app">
      <nav className="nav-bar">
        <button className="nav-home-btn" onClick={() => navigate('/learn')} aria-label="Home">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </button>

        <span className="nav-center">
          <svg className="nav-logo" width="28" height="28" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#667eea"/>
                <stop offset="100%" stopColor="#764ba2"/>
              </linearGradient>
            </defs>
            {/* Open book */}
            <path d="M8 44 C8 40, 16 36, 32 38 C48 36, 56 40, 56 44 L56 52 C56 50, 48 48, 32 50 C16 48, 8 50, 8 52 Z" fill="url(#logoGrad)" opacity="0.85"/>
            <line x1="32" y1="38" x2="32" y2="50" stroke="white" strokeWidth="1.2" opacity="0.6"/>
            {/* Wand */}
            <line x1="32" y1="36" x2="32" y2="16" stroke="url(#logoGrad)" strokeWidth="2.5" strokeLinecap="round"/>
            {/* Star at wand tip */}
            <polygon points="32,8 34,14 40,14 35,18 37,24 32,20 27,24 29,18 24,14 30,14" fill="url(#logoGrad)"/>
            {/* Sparkles */}
            <circle cx="20" cy="16" r="1.8" fill="#667eea" opacity="0.7"/>
            <circle cx="44" cy="12" r="1.5" fill="#764ba2" opacity="0.6"/>
            <circle cx="46" cy="24" r="1.2" fill="#667eea" opacity="0.5"/>
            <circle cx="18" cy="26" r="1.3" fill="#764ba2" opacity="0.5"/>
            {/* Sparkle crosses */}
            <g stroke="#667eea" strokeWidth="1.2" opacity="0.7">
              <line x1="22" y1="22" x2="22" y2="26"/>
              <line x1="20" y1="24" x2="24" y2="24"/>
            </g>
            <g stroke="#764ba2" strokeWidth="1.2" opacity="0.6">
              <line x1="42" y1="18" x2="42" y2="22"/>
              <line x1="40" y1="20" x2="44" y2="20"/>
            </g>
          </svg>
          Learn Like Magic
        </span>

        <div className="nav-user-menu" ref={menuRef}>
          <button
            className="nav-user-btn"
            onClick={() => setShowUserMenu(!showUserMenu)}
            aria-label="User menu"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </button>
          {showUserMenu && (
            <div className="nav-dropdown">
              <button className="nav-dropdown-item" onClick={() => { setShowUserMenu(false); navigate('/profile'); }}>
                Profile
              </button>
              <button className="nav-dropdown-item" onClick={() => { setShowUserMenu(false); navigate('/history'); }}>
                My Sessions
              </button>
              <button className="nav-dropdown-item" onClick={() => { setShowUserMenu(false); navigate('/scorecard'); }}>
                My Scorecard
              </button>
              <button className="nav-dropdown-item nav-dropdown-item--danger" onClick={handleLogout}>
                Log Out
              </button>
            </div>
          )}
        </div>
      </nav>

      <div className="app-content">
        <Outlet />
      </div>
    </div>
  );
}
