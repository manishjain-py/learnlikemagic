/**
 * SessionHistoryPage — View past learning sessions.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface SessionEntry {
  session_id: string;
  created_at: string;
  updated_at: string;
  topic_name: string | null;
  subject: string | null;
  mastery: number;
  step_idx: number;
  mode?: string;
  coverage?: number;
  concepts_discussed?: string[];
}

interface LearningStats {
  total_sessions: number;
  average_mastery: number;
  topics_covered: string[];
  total_steps: number;
}

export default function SessionHistoryPage() {
  const navigate = useNavigate();
  const { token } = useAuth();
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [stats, setStats] = useState<LearningStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [modeFilter, setModeFilter] = useState<string>('all');

  const getModeLabel = (mode: string) => {
    switch (mode) {
      case 'teach_me': return 'Teach Me';
      case 'clarify_doubts': return 'Clarify Doubts';
      default: return 'Teach Me';
    }
  };

  const getModeBadgeColor = (mode: string) => {
    switch (mode) {
      case 'teach_me': return '#667eea';
      case 'clarify_doubts': return '#38a169';
      default: return '#667eea';
    }
  };

  useEffect(() => {
    fetchHistory();
    fetchStats();
  }, [page]);

  const fetchHistory = async () => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/sessions/history?page=${page}&page_size=10`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions);
        setTotal(data.total);
      }
    } catch (err) {
      console.error('Failed to fetch history:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/sessions/stats`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        setStats(await response.json());
      }
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-IN', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const getMasteryColor = (mastery: number) => {
    if (mastery >= 0.8) return '#4caf50';
    if (mastery >= 0.5) return '#ff9800';
    return '#f44336';
  };

  return (
    <div className="app-content-inner">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 className="page-title">My Sessions</h2>
        <button
          className="auth-link"
          onClick={() => navigate('/report-card')}
          style={{ fontSize: '0.85rem' }}
        >
          View Report Card &rarr;
        </button>
      </div>

      {/* Stats summary */}
      {stats && stats.total_sessions > 0 && (
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-value">{stats.total_sessions}</span>
            <span className="stat-label">Sessions</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{(stats.average_mastery * 100).toFixed(0)}%</span>
            <span className="stat-label">Avg Mastery</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{stats.topics_covered.length}</span>
            <span className="stat-label">Topics</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{stats.total_steps}</span>
            <span className="stat-label">Steps</span>
          </div>
        </div>
      )}

      <div className="mode-filter-group">
        {['all', 'teach_me', 'clarify_doubts'].map((mode) => (
          <button
            key={mode}
            onClick={() => setModeFilter(mode)}
            className={`mode-filter-btn${modeFilter === mode ? ' mode-filter-btn--active' : ''}`}
          >
            {mode === 'all' ? 'All' : getModeLabel(mode)}
          </button>
        ))}
      </div>

      {/* Session list */}
      {loading ? (
        <p className="page-loading">Loading...</p>
      ) : sessions.length === 0 ? (
        <div className="page-empty-state">
          <p className="page-empty-state-title">No sessions yet</p>
          <p className="page-empty-state-desc">Start learning to see your history here</p>
          <button
            className="auth-btn auth-btn-primary"
            onClick={() => navigate('/')}
            style={{ marginTop: '16px' }}
          >
            Start a Session
          </button>
        </div>
      ) : (
        <>
          <div className="session-list">
            {sessions
              .filter((s) => modeFilter === 'all' || s.mode === modeFilter)
              .map((session) => (
              <div key={session.session_id} className="session-card">
                <div className="session-card-header">
                  <span className="session-topic">
                    {session.topic_name || 'Unknown Topic'}
                  </span>
                  <span
                    className="mode-badge"
                    style={{ background: getModeBadgeColor(session.mode || 'teach_me') }}
                  >
                    {getModeLabel(session.mode || 'teach_me')}
                  </span>
                  <span
                    className="session-mastery"
                    style={{ color: getMasteryColor(session.mastery) }}
                  >
                    {session.mode === 'clarify_doubts' && session.concepts_discussed
                      ? `${session.concepts_discussed.length} concepts`
                      : `${(session.mastery * 100).toFixed(0)}%`}
                  </span>
                </div>
                <div className="session-card-meta">
                  {session.subject && (
                    <span className="session-subject">{session.subject}</span>
                  )}
                  <span className="session-date">{formatDate(session.created_at)}</span>
                  <span className="session-steps">{session.step_idx} steps</span>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {total > 10 && (
            <div className="pagination">
              <button
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
                className="auth-link"
              >
                Previous
              </button>
              <span>Page {page} of {Math.ceil(total / 10)}</span>
              <button
                disabled={page * 10 >= total}
                onClick={() => setPage(page + 1)}
                className="auth-link"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
