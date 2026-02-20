/**
 * ScorecardPage — Aggregated student performance view.
 *
 * Overview: overall score, strengths, needs-practice, subject cards, trend chart.
 * Subject detail: trend chart, topic sections with expandable subtopics.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import {
  getScorecard,
  createSession,
  ScorecardResponse,
  ScorecardSubject,
  ScorecardTopic,
  ScorecardSubtopic,
  ScorecardHighlight,
} from '../api';
import { useAuth } from '../contexts/AuthContext';

// ── Helpers ────────────────────────────────────────

const SUBJECT_COLORS = ['#667eea', '#38a169', '#e53e3e', '#ff9800', '#764ba2', '#2196f3'];

function getMasteryLabel(score: number): { label: string; colorClass: string } {
  if (score >= 0.85) return { label: 'Mastered', colorClass: 'mastered' };
  if (score >= 0.65) return { label: 'Getting Strong', colorClass: 'getting-strong' };
  if (score >= 0.45) return { label: 'Getting There', colorClass: 'getting-there' };
  return { label: 'Needs Practice', colorClass: 'needs-practice' };
}

function getMasteryColor(score: number): string {
  if (score >= 0.85) return '#38a169';
  if (score >= 0.65) return '#667eea';
  if (score >= 0.45) return '#ff9800';
  return '#e53e3e';
}

function formatPercent(score: number): string {
  return `${(score * 100).toFixed(0)}%`;
}

// ── Sub-components ─────────────────────────────────

function MasteryBar({ score }: { score: number }) {
  return (
    <div className="mastery-bar">
      <div
        className="mastery-bar-fill"
        style={{ width: `${score * 100}%`, background: getMasteryColor(score) }}
      />
    </div>
  );
}

function MasteryBadge({ score }: { score: number }) {
  const { label, colorClass } = getMasteryLabel(score);
  return <span className={`mastery-badge ${colorClass}`}>{label}</span>;
}

function OverallHero({ data }: { data: ScorecardResponse }) {
  const color = getMasteryColor(data.overall_score);
  const { label } = getMasteryLabel(data.overall_score);
  const pct = Math.round(data.overall_score * 100);
  // SVG circle progress
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (data.overall_score * circumference);

  return (
    <div className="scorecard-hero">
      <div className="scorecard-hero-score">
        <svg width="100" height="100" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r={radius} fill="none" stroke="#e0e0e0" strokeWidth="8" />
          <circle
            cx="50" cy="50" r={radius} fill="none"
            stroke={color} strokeWidth="8"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 50 50)"
            style={{ transition: 'stroke-dashoffset 0.5s ease' }}
          />
          <text x="50" y="46" textAnchor="middle" fontSize="20" fontWeight="700" fill={color}>
            {pct}%
          </text>
          <text x="50" y="62" textAnchor="middle" fontSize="9" fill="#888">
            overall
          </text>
        </svg>
      </div>
      <div className="scorecard-hero-info">
        <span className="scorecard-hero-label" style={{ color }}>{label}</span>
        <span className="scorecard-hero-stats">
          {data.total_sessions} session{data.total_sessions !== 1 ? 's' : ''}
          {' \u00B7 '}
          {data.total_topics_studied} topic{data.total_topics_studied !== 1 ? 's' : ''} studied
        </span>
      </div>
    </div>
  );
}

function HighlightList({
  title,
  items,
  type,
}: {
  title: string;
  items: ScorecardHighlight[];
  type: 'strength' | 'needs-practice';
}) {
  if (items.length === 0) return null;
  return (
    <div className="scorecard-section">
      <h3 className="scorecard-section-title">{title}</h3>
      <div className={`scorecard-highlights ${type}`}>
        {items.map((item, i) => (
          <div key={i} className="scorecard-highlight-row">
            <span className="scorecard-highlight-icon">
              {type === 'strength' ? '\u2713' : '\u26A0'}
            </span>
            <span className="scorecard-highlight-name">{item.subtopic}</span>
            <span
              className="scorecard-highlight-score"
              style={{ color: getMasteryColor(item.score) }}
            >
              {formatPercent(item.score)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SubjectCards({
  subjects,
  onSelect,
}: {
  subjects: ScorecardSubject[];
  onSelect: (s: ScorecardSubject) => void;
}) {
  return (
    <div className="scorecard-section">
      <h3 className="scorecard-section-title">Subjects</h3>
      <div className="scorecard-subject-grid">
        {subjects.map((subject, i) => (
          <button
            key={subject.subject}
            className="scorecard-subject-card"
            onClick={() => onSelect(subject)}
          >
            <div className="scorecard-subject-card-header">
              <span className="scorecard-subject-name">{subject.subject}</span>
              <span
                className="scorecard-subject-score"
                style={{ color: getMasteryColor(subject.score) }}
              >
                {formatPercent(subject.score)}
              </span>
            </div>
            <MasteryBar score={subject.score} />
            <span className="scorecard-subject-meta">
              {subject.topics.length} topic{subject.topics.length !== 1 ? 's' : ''}
              {' \u00B7 '}
              {subject.session_count} session{subject.session_count !== 1 ? 's' : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TrendChart({
  subjects,
  singleSubject,
}: {
  subjects: ScorecardSubject[];
  singleSubject?: boolean;
}) {
  // Build unified chart data
  // Collect all unique dates, then for each date fill in each subject's score
  const allPoints: Record<string, Record<string, number>> = {};
  subjects.forEach((subj) => {
    subj.trend.forEach((pt) => {
      const key = pt.date_label || pt.date || '';
      if (!allPoints[key]) allPoints[key] = { _idx: 0 } as any;
      allPoints[key][subj.subject] = Math.round(pt.score * 100);
    });
  });

  // Convert to array preserving order
  const labelOrder: string[] = [];
  subjects.forEach((subj) => {
    subj.trend.forEach((pt) => {
      const key = pt.date_label || pt.date || '';
      if (!labelOrder.includes(key)) labelOrder.push(key);
    });
  });

  const chartData = labelOrder.map((label) => ({
    date_label: label,
    ...allPoints[label],
  }));

  if (chartData.length < 2) return null;

  return (
    <div className="scorecard-section">
      <h3 className="scorecard-section-title">
        {singleSubject ? 'Mastery Trend' : 'Recent Progress'}
      </h3>
      <div className="scorecard-chart">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="date_label" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `${v}%`} />
            {!singleSubject && subjects.length > 1 && <Legend />}
            {subjects.map((subj, i) => (
              <Line
                key={subj.subject}
                dataKey={subj.subject}
                stroke={SUBJECT_COLORS[i % SUBJECT_COLORS.length]}
                dot={subjects.length === 1}
                strokeWidth={2}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function SubtopicDetail({
  subtopic,
  subject,
  onPractice,
  practicing,
}: {
  subtopic: ScorecardSubtopic;
  subject: string;
  onPractice: (subtopic: ScorecardSubtopic, subject: string) => void;
  practicing: boolean;
}) {
  const concepts = Object.entries(subtopic.concepts);
  const misconceptions = subtopic.misconceptions;

  return (
    <div className="scorecard-subtopic-detail">
      {concepts.length > 0 && (
        <div className="scorecard-concepts">
          <span className="scorecard-detail-label">Concepts:</span>
          {concepts.map(([name, score]) => (
            <div key={name} className="scorecard-concept-row">
              <span className="scorecard-concept-name">{name}</span>
              <span
                className="scorecard-concept-score"
                style={{ color: getMasteryColor(score) }}
              >
                {formatPercent(score)}
              </span>
            </div>
          ))}
        </div>
      )}
      {misconceptions.length > 0 && (
        <div className="scorecard-misconceptions">
          <span className="scorecard-detail-label">Misconceptions:</span>
          {misconceptions.map((m, i) => (
            <div key={i} className={`scorecard-misconception ${m.resolved ? 'resolved' : ''}`}>
              <span>{m.description}</span>
              <span className="scorecard-misconception-status">
                {m.resolved ? 'Resolved' : 'Active'}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="scorecard-subtopic-meta">
        {subtopic.session_count} session{subtopic.session_count !== 1 ? 's' : ''}
        {subtopic.latest_session_date && (
          <> &middot; Last: {new Date(subtopic.latest_session_date).toLocaleDateString('en-IN', {
            month: 'short', day: 'numeric', year: 'numeric',
          })}</>
        )}
      </div>
      {subtopic.guideline_id && (
        <button
          className="practice-again-btn"
          onClick={() => onPractice(subtopic, subject)}
          disabled={practicing}
        >
          {practicing ? 'Starting...' : 'Practice Again'}
        </button>
      )}
    </div>
  );
}

function TopicSection({
  topic,
  subject,
  expandedSubtopics,
  toggleSubtopic,
  onPractice,
  practicing,
}: {
  topic: ScorecardTopic;
  subject: string;
  expandedSubtopics: Set<string>;
  toggleSubtopic: (key: string) => void;
  onPractice: (subtopic: ScorecardSubtopic, subject: string) => void;
  practicing: boolean;
}) {
  return (
    <div className="scorecard-topic-section">
      <div className="scorecard-topic-header">
        <span className="scorecard-topic-name">{topic.topic}</span>
        <span
          className="scorecard-topic-score"
          style={{ color: getMasteryColor(topic.score) }}
        >
          {formatPercent(topic.score)}
        </span>
      </div>
      <div className="scorecard-subtopic-list">
        {topic.subtopics.map((st) => {
          const key = `${topic.topic_key}/${st.subtopic_key}`;
          const expanded = expandedSubtopics.has(key);
          return (
            <div key={st.subtopic_key} className="scorecard-subtopic-row">
              <button
                className="scorecard-subtopic-toggle"
                onClick={() => toggleSubtopic(key)}
              >
                <span className="scorecard-subtopic-name">{st.subtopic}</span>
                <span className="scorecard-subtopic-right">
                  <MasteryBadge score={st.score} />
                  <span
                    className="scorecard-subtopic-score"
                    style={{ color: getMasteryColor(st.score) }}
                  >
                    {formatPercent(st.score)}
                  </span>
                  <span className="scorecard-chevron">{expanded ? '\u25BC' : '\u25B6'}</span>
                </span>
              </button>
              <MasteryBar score={st.score} />
              {expanded && (
                <SubtopicDetail
                  subtopic={st}
                  subject={subject}
                  onPractice={onPractice}
                  practicing={practicing}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SubjectDetailView({
  subject,
  onBack,
  onPractice,
  practicing,
}: {
  subject: ScorecardSubject;
  onBack: () => void;
  onPractice: (subtopic: ScorecardSubtopic, subjectName: string) => void;
  practicing: boolean;
}) {
  const [expandedSubtopics, setExpandedSubtopics] = useState<Set<string>>(new Set());

  const toggleSubtopic = (key: string) => {
    setExpandedSubtopics((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Collect all misconceptions for this subject
  const allMisconceptions: { description: string; resolved: boolean; topic: string }[] = [];
  subject.topics.forEach((t) => {
    t.subtopics.forEach((st) => {
      st.misconceptions.forEach((m) => {
        allMisconceptions.push({ ...m, topic: t.topic });
      });
    });
  });

  return (
    <>
      <button className="auth-back-btn" onClick={onBack}>
        &larr; Scorecard
      </button>
      <div className="scorecard-subject-header">
        <h2 className="auth-title">{subject.subject}</h2>
        <span
          className="scorecard-subject-detail-score"
          style={{ color: getMasteryColor(subject.score) }}
        >
          {formatPercent(subject.score)}
        </span>
      </div>

      <TrendChart subjects={[subject]} singleSubject />

      <div className="scorecard-section">
        <h3 className="scorecard-section-title">Topics</h3>
        {subject.topics.map((topic) => (
          <TopicSection
            key={topic.topic_key}
            topic={topic}
            subject={subject.subject}
            expandedSubtopics={expandedSubtopics}
            toggleSubtopic={toggleSubtopic}
            onPractice={onPractice}
            practicing={practicing}
          />
        ))}
      </div>

      {allMisconceptions.length > 0 && (
        <div className="scorecard-section">
          <h3 className="scorecard-section-title">Misconceptions</h3>
          <div className="scorecard-misconceptions-list">
            {allMisconceptions.map((m, i) => (
              <div key={i} className={`scorecard-misconception ${m.resolved ? 'resolved' : ''}`}>
                <span>{m.description}</span>
                <span className="scorecard-misconception-meta">
                  {m.topic} &middot; {m.resolved ? 'Resolved \u2713' : 'Active \u25CF'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// ── Main Page ──────────────────────────────────────

export default function ScorecardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<ScorecardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubject, setSelectedSubject] = useState<ScorecardSubject | null>(null);
  const [practicing, setPracticing] = useState(false);

  useEffect(() => {
    fetchScorecard();
  }, []);

  const fetchScorecard = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getScorecard();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch scorecard:', err);
      setError('Failed to load scorecard. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handlePracticeAgain = async (subtopic: ScorecardSubtopic, subject: string) => {
    if (!user || !subtopic.guideline_id) return;
    setPracticing(true);
    try {
      const response = await createSession({
        student: {
          id: user.id,
          grade: user.grade || 3,
          prefs: { style: 'standard', lang: 'en' },
        },
        goal: {
          topic: subtopic.subtopic,
          syllabus: `${user.board || 'CBSE'}-G${user.grade || 3}`,
          learning_objectives: [],
          guideline_id: subtopic.guideline_id,
        },
      });
      // Navigate to tutor with the new session
      navigate('/', { state: { sessionId: response.session_id } });
    } catch (err) {
      console.error('Failed to start session:', err);
    } finally {
      setPracticing(false);
    }
  };

  // Loading state
  if (loading) {
    return (
      <div className="auth-page">
        <div className="auth-container scorecard-page">
          <button className="auth-back-btn" onClick={() => navigate('/')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Scorecard</h2>
          <p style={{ textAlign: 'center', padding: '2rem', color: '#888' }}>Loading...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="auth-page">
        <div className="auth-container scorecard-page">
          <button className="auth-back-btn" onClick={() => navigate('/')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Scorecard</h2>
          <div className="auth-error">{error}</div>
          <button className="auth-btn auth-btn-primary" onClick={fetchScorecard}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state
  if (!data || data.total_sessions === 0) {
    return (
      <div className="auth-page">
        <div className="auth-container scorecard-page">
          <button className="auth-back-btn" onClick={() => navigate('/')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Scorecard</h2>
          <div style={{ textAlign: 'center', padding: '3rem 1rem' }}>
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>&#128202;</div>
            <p style={{ fontSize: '1.1rem', color: '#333', marginBottom: '8px' }}>
              Your scorecard is empty!
            </p>
            <p style={{ color: '#888', marginBottom: '20px' }}>
              Complete a learning session to see how you're doing across subjects and topics.
            </p>
            <button
              className="auth-btn auth-btn-primary"
              onClick={() => navigate('/')}
            >
              Start Learning
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Subject detail view
  if (selectedSubject) {
    return (
      <div className="auth-page">
        <div className="auth-container scorecard-page">
          <SubjectDetailView
            subject={selectedSubject}
            onBack={() => setSelectedSubject(null)}
            onPractice={handlePracticeAgain}
            practicing={practicing}
          />
        </div>
      </div>
    );
  }

  // Overview
  return (
    <div className="auth-page">
      <div className="auth-container scorecard-page">
        <button className="auth-back-btn" onClick={() => navigate('/')}>
          &larr; Back
        </button>
        <h2 className="auth-title">My Scorecard</h2>

        <OverallHero data={data} />
        <HighlightList title="Strengths" items={data.strengths} type="strength" />
        <HighlightList title="Needs Practice" items={data.needs_practice} type="needs-practice" />
        <SubjectCards subjects={data.subjects} onSelect={setSelectedSubject} />
        <TrendChart subjects={data.subjects} />
      </div>
    </div>
  );
}
