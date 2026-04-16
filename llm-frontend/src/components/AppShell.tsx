import React, { useState, useEffect, useRef } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import '../App.css';

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Chalkboard theme scope: all student-facing AppShell routes.
  // Admin routes (/admin/*) are NOT wrapped by AppShell so they're
  // unaffected.
  const isChalkboardRoute =
    location.pathname.startsWith('/learn') ||
    location.pathname.startsWith('/history') ||
    location.pathname.startsWith('/report-card') ||
    location.pathname.startsWith('/profile') ||
    location.pathname.startsWith('/report-issue');

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
    <div className={`app${isChalkboardRoute ? ' chalkboard-active' : ''}`}>
      <nav className="nav-bar">
        <button className="nav-home-btn" onClick={() => navigate('/learn')} aria-label="Home">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </button>

        <span className="nav-center">
          <svg className="nav-logo" width="28" height="28" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            {/* Chalk book */}
            <path d="M10 22 L40 18 L70 22 L70 60 L40 56 L10 60 Z" stroke="currentColor" strokeWidth="2" fill="none" strokeLinejoin="round"/>
            <path d="M40 18 L40 56" stroke="currentColor" strokeWidth="2"/>
            <path d="M16 30 L34 27 M16 36 L34 33" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            <path d="M46 27 L64 30 M46 33 L64 36" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            {/* Wand + star — gold */}
            <line x1="55" y1="10" x2="30" y2="38" stroke="#F4C76C" strokeWidth="3" strokeLinecap="round"/>
            <path d="M58 6 L61 12 L67 13 L62.5 17 L64 23 L58 20 L52 23 L53.5 17 L49 13 L55 12 Z" fill="#F4C76C"/>
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
              <button className="nav-dropdown-item" onClick={() => { setShowUserMenu(false); navigate('/report-card'); }}>
                My Report Card
              </button>
              <button className="nav-dropdown-item" onClick={() => { setShowUserMenu(false); navigate('/report-issue'); }}>
                Report an Issue
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
