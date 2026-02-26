/**
 * ScorecardPage — Deterministic student report card.
 *
 * Shows coverage % and exam scores per subtopic. No AI-interpreted metrics.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getScorecard,
  createSession,
  ReportCardResponse,
  ReportCardSubject,
  ReportCardTopic,
  ReportCardSubtopic,
} from '../api';
import { useAuth } from '../contexts/AuthContext';

// ── Sub-components ─────────────────────────────────

function SubjectCards({
  subjects,
  onSelect,
}: {
  subjects: ReportCardSubject[];
  onSelect: (s: ReportCardSubject) => void;
}) {
  return (
    <div className="scorecard-section">
      <h3 className="scorecard-section-title">Subjects</h3>
      <div className="scorecard-subject-grid">
        {subjects.map((subject) => (
          <button
            key={subject.subject}
            className="scorecard-subject-card"
            data-testid="scorecard-subject-card"
            onClick={() => onSelect(subject)}
          >
            <div className="scorecard-subject-card-header">
              <span className="scorecard-subject-name">{subject.subject}</span>
            </div>
            <span className="scorecard-subject-meta">
              {subject.topics.length} topic{subject.topics.length !== 1 ? 's' : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TopicSection({
  topic,
  subject,
  onPractice,
  practicing,
}: {
  topic: ReportCardTopic;
  subject: string;
  onPractice: (subtopic: ReportCardSubtopic, subject: string) => void;
  practicing: boolean;
}) {
  return (
    <div className="scorecard-topic-section">
      <div className="scorecard-topic-header">
        <span className="scorecard-topic-name">{topic.topic}</span>
      </div>
      <div className="scorecard-subtopic-list">
        {topic.subtopics.map((st) => (
          <div key={st.subtopic_key} className="scorecard-subtopic-row">
            <div className="scorecard-subtopic-toggle">
              <span className="scorecard-subtopic-name">{st.subtopic}</span>
              <span className="scorecard-subtopic-right">
                <span className="scorecard-coverage">
                  {st.coverage.toFixed(0)}% covered
                </span>
                {st.latest_exam_score != null && st.latest_exam_total != null && (
                  <span className="scorecard-exam-score">
                    {st.latest_exam_score}/{st.latest_exam_total}
                  </span>
                )}
              </span>
            </div>
            <div className="coverage-bar">
              <div
                className="coverage-bar-fill"
                style={{ width: `${st.coverage}%` }}
              />
            </div>
            <div className="scorecard-subtopic-detail">
              {st.last_studied && (
                <span className="scorecard-subtopic-meta">
                  Last studied: {new Date(st.last_studied).toLocaleDateString('en-IN', {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}
                </span>
              )}
              {st.guideline_id && (
                <button
                  className="practice-again-btn"
                  onClick={() => onPractice(st, subject)}
                  disabled={practicing}
                >
                  {practicing ? 'Starting...' : 'Practice Again'}
                </button>
              )}
            </div>
          </div>
        ))}
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
  subject: ReportCardSubject;
  onBack: () => void;
  onPractice: (subtopic: ReportCardSubtopic, subjectName: string) => void;
  practicing: boolean;
}) {
  return (
    <>
      <button className="auth-back-btn" onClick={onBack}>
        &larr; Report Card
      </button>
      <div className="scorecard-subject-header">
        <h2 className="auth-title">{subject.subject}</h2>
      </div>

      <div className="scorecard-section">
        <h3 className="scorecard-section-title">Topics</h3>
        {subject.topics.map((topic) => (
          <TopicSection
            key={topic.topic_key}
            topic={topic}
            subject={subject.subject}
            onPractice={onPractice}
            practicing={practicing}
          />
        ))}
      </div>
    </>
  );
}

// ── Main Page ──────────────────────────────────────

export default function ScorecardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<ReportCardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubject, setSelectedSubject] = useState<ReportCardSubject | null>(null);
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
      console.error('Failed to fetch report card:', err);
      setError('Failed to load report card. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handlePracticeAgain = async (subtopic: ReportCardSubtopic, subject: string) => {
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
      navigate(`/session/${response.session_id}`, {
        state: { firstTurn: response.first_turn, mode: 'teach_me', subject },
      });
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
          <button className="auth-back-btn" onClick={() => navigate('/learn')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Report Card</h2>
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
          <button className="auth-back-btn" onClick={() => navigate('/learn')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Report Card</h2>
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
          <button className="auth-back-btn" onClick={() => navigate('/learn')}>
            &larr; Back
          </button>
          <h2 className="auth-title">My Report Card</h2>
          <div style={{ textAlign: 'center', padding: '3rem 1rem' }}>
            <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>&#128202;</div>
            <p style={{ fontSize: '1.1rem', color: '#333', marginBottom: '8px' }}>
              Your report card is empty!
            </p>
            <p style={{ color: '#888', marginBottom: '20px' }}>
              Complete a learning session to see your progress across subjects and topics.
            </p>
            <button
              className="auth-btn auth-btn-primary"
              onClick={() => navigate('/learn')}
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
        <button className="auth-back-btn" onClick={() => navigate('/learn')}>
          &larr; Back
        </button>
        <h2 className="auth-title">My Report Card</h2>
        <p className="scorecard-stats-line">
          {data.total_sessions} session{data.total_sessions !== 1 ? 's' : ''}
          {' \u00B7 '}
          {data.total_topics_studied} topic{data.total_topics_studied !== 1 ? 's' : ''} studied
        </p>

        <SubjectCards subjects={data.subjects} onSelect={setSelectedSubject} />
      </div>
    </div>
  );
}
