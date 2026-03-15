/**
 * AdminLayout — Shared layout wrapper for all admin pages.
 * Renders a persistent top nav bar with links to every admin section.
 */

import React from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

interface NavItem {
  label: string;
  path: string;
  /** Match prefix — active when location starts with this path */
  matchPrefix?: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Books', path: '/admin/books-v2', matchPrefix: '/admin/books-v2' },
  { label: 'Evaluation', path: '/admin/evaluation' },
  { label: 'Test Scenarios', path: '/admin/test-scenarios' },
  { label: 'LLM Config', path: '/admin/llm-config' },
  { label: 'Docs', path: '/admin/docs' },
  { label: 'Pixi.js PoC', path: '/admin/pixi-js-poc' },
  { label: 'Feature Flags', path: '/admin/feature-flags' },
];

const AdminLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const isActive = (item: NavItem) => {
    const prefix = item.matchPrefix || item.path;
    return location.pathname === prefix || location.pathname.startsWith(prefix + '/');
  };

  const isHome = location.pathname === '/admin';

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#F9FAFB' }}>
      {/* Top nav bar */}
      <nav style={{
        backgroundColor: 'white',
        borderBottom: '1px solid #E5E7EB',
        padding: '0 24px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}>
        <div style={{
          maxWidth: '1400px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          height: '56px',
          gap: '8px',
        }}>
          {/* Home / brand */}
          <button
            onClick={() => navigate('/admin')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 12px',
              backgroundColor: isHome ? '#EEF2FF' : 'transparent',
              color: isHome ? '#4F46E5' : '#374151',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '15px',
              marginRight: '12px',
              whiteSpace: 'nowrap',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
            Admin
          </button>

          {/* Divider */}
          <div style={{ width: '1px', height: '24px', backgroundColor: '#E5E7EB', marginRight: '4px' }} />

          {/* Nav links */}
          <div style={{ display: 'flex', gap: '2px', overflowX: 'auto' }}>
            {NAV_ITEMS.map((item) => {
              const active = isActive(item);
              return (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  style={{
                    padding: '8px 14px',
                    backgroundColor: active ? '#EEF2FF' : 'transparent',
                    color: active ? '#4F46E5' : '#6B7280',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '14px',
                    fontWeight: active ? 600 : 500,
                    whiteSpace: 'nowrap',
                    transition: 'background-color 0.15s, color 0.15s',
                  }}
                  onMouseEnter={(e) => {
                    if (!active) {
                      e.currentTarget.style.backgroundColor = '#F3F4F6';
                      e.currentTarget.style.color = '#374151';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!active) {
                      e.currentTarget.style.backgroundColor = 'transparent';
                      e.currentTarget.style.color = '#6B7280';
                    }
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
      </nav>

      {/* Page content */}
      <main>
        <Outlet />
      </main>
    </div>
  );
};

export default AdminLayout;
