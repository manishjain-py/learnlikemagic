/**
 * ReportCardPage — Deterministic student report card.
 *
 * Shows coverage % and exam scores per topic. No AI-interpreted metrics.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getReportCard,
  createSession,
  ReportCardResponse,
  ReportCardSubject,
  ReportCardChapter,
  ReportCardTopic,
} from '../api';
import { useAuth } from '../contexts/AuthContext';

// -- Sub-components --

function SubjectCards({
  subjects,
  onSelect,
}: {
  subjects: ReportCardSubject[];
  onSelect: (s: ReportCardSubject) => void;
}) {
  return (
    <div className="reportcard-section">
      <h3 className="reportcard-section-title">Subjects</h3>
      <div className="reportcard-subject-grid">
        {subjects.map((subject) => (
          <button
            key={subject.subject}
            className="reportcard-subject-card"
            data-testid="reportcard-subject-card"
            onClick={() => onSelect(subject)}
          >
            <div className="reportcard-subject-card-header">
              <span className="reportcard-subject-name">{subject.subject}</span>
            </div>
            <span className="reportcard-subject-meta">
              {subject.chapters.length} chapter{subject.chapters.length !== 1 ? 's' : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ChapterSection({
  chapter,
  subject,
  onPractice,
  practicing,
}: {
  chapter: ReportCardChapter;
  subject: string;
  onPractice: (topic: ReportCardTopic, subject: string) => void;
  practicing: boolean;
}) {
  return (
    <div className="reportcard-chapter-section">
      <div className="reportcard-chapter-header">
        <span className="reportcard-chapter-name">{chapter.chapter}</span>
      </div>
      <div className="reportcard-topic-list">
        {chapter.topics.map((st) => (
          <div key={st.topic_key} className="reportcard-topic-row">
            <div className="reportcard-topic-toggle">
              <span className="reportcard-topic-name">{st.topic}</span>
              <span className="reportcard-topic-right">
                <span className="reportcard-coverage">
                  {(st.coverage ?? 0).toFixed(0)}% covered
                </span>
                {st.latest_exam_score != null && st.latest_exam_total != null && (
                  <span className="reportcard-exam-score">
                    {st.latest_exam_score}/{st.latest_exam_total}
                  </span>
                )}
              </span>
            </div>
            <div className="coverage-bar">
              <div
                className="coverage-bar-fill"
                style={{ width: `${Math.min(st.coverage ?? 0, 100)}%` }}
              />
            </div>
            <div className="reportcard-topic-detail">
              {st.last_studied && (
                <span className="reportcard-topic-meta">
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
  onPractice: (topic: ReportCardTopic, subjectName: string) => void;
  practicing: boolean;
}) {
  return (
    <>
      <button className="content-back-link" onClick={onBack}>
        &larr; Report Card
      </button>
      <div className="reportcard-subject-header">
        <h2 className="page-title">{subject.subject}</h2>
      </div>

      <div className="reportcard-section">
        <h3 className="reportcard-section-title">Chapters</h3>
        {subject.chapters.map((chapter) => (
          <ChapterSection
            key={chapter.chapter_key}
            chapter={chapter}
            subject={subject.subject}
            onPractice={onPractice}
            practicing={practicing}
          />
        ))}
      </div>
    </>
  );
}

// -- Main Page --

export default function ReportCardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<ReportCardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubject, setSelectedSubject] = useState<ReportCardSubject | null>(null);
  const [practicing, setPracticing] = useState(false);

  useEffect(() => {
    fetchReportCard();
  }, []);

  const fetchReportCard = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getReportCard();
      setData(result);
    } catch (err) {
      console.error('Failed to fetch report card:', err);
      setError('Failed to load report card. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handlePracticeAgain = async (topic: ReportCardTopic, subject: string) => {
    if (!user || !topic.guideline_id) return;
    setPracticing(true);
    try {
      const response = await createSession({
        student: {
          id: user.id,
          grade: user.grade || 3,
          prefs: { style: 'standard', lang: 'en' },
        },
        goal: {
          chapter: topic.topic,
          syllabus: `${user.board || 'CBSE'}-G${user.grade || 3}`,
          learning_objectives: [],
          guideline_id: topic.guideline_id,
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
      <div className="app-content-inner">
        <h2 className="page-title">My Report Card</h2>
        <p className="page-loading">Loading...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="app-content-inner">
        <h2 className="page-title">My Report Card</h2>
        <div className="auth-error">{error}</div>
        <button className="auth-btn auth-btn-primary" onClick={fetchReportCard}>
          Retry
        </button>
      </div>
    );
  }

  // Empty state
  if (!data || data.total_sessions === 0) {
    return (
      <div className="app-content-inner">
        <h2 className="page-title">My Report Card</h2>
        <div className="page-empty-state">
          <div className="page-empty-state-icon">&#128202;</div>
          <p className="page-empty-state-title">Your report card is empty!</p>
          <p className="page-empty-state-desc">
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
    );
  }

  // Subject detail view
  if (selectedSubject) {
    return (
      <div className="app-content-inner">
        <SubjectDetailView
          subject={selectedSubject}
          onBack={() => setSelectedSubject(null)}
          onPractice={handlePracticeAgain}
          practicing={practicing}
        />
      </div>
    );
  }

  // Overview
  return (
    <div className="app-content-inner">
      <h2 className="page-title">My Report Card</h2>
      <p className="reportcard-stats-line">
        {data.total_sessions} session{data.total_sessions !== 1 ? 's' : ''}
        {' \u00B7 '}
        {data.total_chapters_studied} chapter{data.total_chapters_studied !== 1 ? 's' : ''} studied
      </p>

      <SubjectCards subjects={data.subjects} onSelect={setSelectedSubject} />
    </div>
  );
}
