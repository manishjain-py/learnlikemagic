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

        <span className="nav-center">Learn Like Magic</span>

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
