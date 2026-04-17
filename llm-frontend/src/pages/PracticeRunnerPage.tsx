import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import QuestionRenderer from '../components/practice/QuestionRenderer';
import {
  getPracticeAttempt, savePracticeAnswer, submitPractice,
  PracticeAttempt, PracticeAttemptQuestion,
} from '../api';

const PATCH_DEBOUNCE_MS = 600;

/**
 * Drill runner — one question at a time, Prev/Next, internal "review my
 * picks" screen, then atomic submit.
 *
 * State management:
 *   - Answers kept in React state keyed by q_idx (string).
 *   - Every onChange schedules a debounced PATCH; AbortController cancels
 *     the in-flight request before the next one fires.
 *   - Submit cancels any pending PATCH, then calls POST /submit with the
 *     full final_answers payload. Server merges, so a late PATCH racing
 *     us would be rejected with 409 rather than silently reverting state.
 *
 * If the attempt is NOT in_progress on mount, redirect to /results.
 */
export default function PracticeRunnerPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const topicTitle = (location.state as { topicTitle?: string } | null)?.topicTitle;

  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [showingReview, setShowingReview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!attemptId) return;
    (async () => {
      try {
        const a = await getPracticeAttempt(attemptId);
        if (a.status !== 'in_progress') {
          navigate(`/practice/attempts/${attemptId}/results`,
            { replace: true, state: { topicTitle } });
          return;
        }
        setAttempt(a as PracticeAttempt);
        setAnswers({ ...(a.answers ?? {}) });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [attemptId, navigate, topicTitle]);

  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
  }, []);

  const handleAnswerChange = useCallback((qIdx: number, value: unknown) => {
    if (!attemptId) return;
    setAnswers(prev => ({ ...prev, [String(qIdx)]: value }));

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      savePracticeAnswer(attemptId, qIdx, value, controller.signal)
        .catch(e => {
          if (controller.signal.aborted) return;
          setError(e instanceof Error ? e.message : String(e));
        });
    }, PATCH_DEBOUNCE_MS);
  }, [attemptId]);

  const handleSubmit = async () => {
    if (!attemptId || !attempt) return;
    setSubmitting(true);
    setError(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    try {
      await submitPractice(attemptId, answers);
      navigate(`/practice/attempts/${attemptId}/results`, { state: { topicTitle } });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="app-content-inner"><p className="page-loading">Loading...</p></div>;
  }
  if (!attempt) {
    return (
      <div className="selection-step">
        <div className="practice-error">{error || 'Attempt not found.'}</div>
      </div>
    );
  }

  const questions = attempt.questions;
  const answeredCount = questions.filter(q => answers[String(q.q_idx)] !== undefined).length;

  if (showingReview) {
    return renderReview({
      attempt, questions, answers, topicTitle,
      onEdit: (idx: number) => { setCurrentIdx(idx); setShowingReview(false); },
      onSubmit: handleSubmit,
      onBack: () => setShowingReview(false),
      submitting, error, answeredCount,
    });
  }

  const q = questions[currentIdx];
  const value = answers[String(q.q_idx)] ?? null;

  return (
    <div className="selection-step">
      <div className="practice-header">
        {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
        <div className="practice-header-row">
          <div className="practice-header-title">
            Question {currentIdx + 1} of {questions.length}
          </div>
          <div style={{ flex: 1 }} />
          <DifficultyDot difficulty={q.difficulty} />
        </div>
        <div className="practice-progress">
          <div className="practice-progress-fill" style={{ width: `${(answeredCount / questions.length) * 100}%` }} />
        </div>
      </div>

      {error && <div className="practice-error">{error}</div>}

      <div className="practice-question-card">
        <QuestionRenderer
          format={q.format}
          questionJson={q.question_json}
          value={value}
          onChange={v => handleAnswerChange(q.q_idx, v)}
          seed={q.presentation_seed}
        />
      </div>

      <div className="practice-nav-row">
        <button
          className="practice-nav-btn practice-nav-btn--ghost"
          onClick={() => setCurrentIdx(i => Math.max(0, i - 1))}
          disabled={currentIdx === 0}
        >
          ← Previous
        </button>
        {currentIdx < questions.length - 1 ? (
          <button
            className="practice-nav-btn practice-nav-btn--primary"
            onClick={() => setCurrentIdx(i => Math.min(questions.length - 1, i + 1))}
          >
            Next →
          </button>
        ) : (
          <button
            className="practice-nav-btn practice-nav-btn--primary"
            onClick={() => setShowingReview(true)}
          >
            Review my picks
          </button>
        )}
      </div>
    </div>
  );
}

function renderReview(opts: {
  attempt: PracticeAttempt;
  questions: PracticeAttemptQuestion[];
  answers: Record<string, unknown>;
  topicTitle?: string;
  onEdit: (idx: number) => void;
  onSubmit: () => void;
  onBack: () => void;
  submitting: boolean;
  error: string | null;
  answeredCount: number;
}) {
  const { questions, answers, topicTitle, onEdit, onSubmit, onBack, submitting, error, answeredCount } = opts;
  return (
    <div className="selection-step">
      {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
      <h2>Review your picks</h2>
      <p className="mode-desc">
        You've answered <strong>{answeredCount} of {questions.length}</strong>.
        Tap any row to edit. Submit when you're ready.
      </p>

      {error && <div className="practice-error">{error}</div>}

      <div style={{ marginBottom: '20px' }}>
        {questions.map((q, i) => {
          const answered = answers[String(q.q_idx)] !== undefined;
          return (
            <div key={q.q_idx} className="practice-review-row">
              <button className="practice-review-btn" onClick={() => onEdit(i)}>
                <span className={`practice-review-tick ${answered ? 'answered' : 'skipped'}`}>
                  {i + 1}
                </span>
                <span className="practice-review-text">
                  {(q.question_json.question_text as string) || '(no question text)'}
                </span>
                <span className={`practice-review-meta practice-review-meta--${answered ? 'answered' : 'skipped'}`}>
                  {answered ? '✓ answered' : 'skipped'}
                </span>
              </button>
            </div>
          );
        })}
      </div>

      <div className="practice-nav-row">
        <button
          className="practice-nav-btn practice-nav-btn--ghost"
          onClick={onBack}
          disabled={submitting}
        >
          ← Back
        </button>
        <button
          className="practice-nav-btn practice-nav-btn--primary"
          onClick={onSubmit}
          disabled={submitting}
        >
          {submitting ? 'Submitting…' : `Submit ${answeredCount}/${questions.length}`}
        </button>
      </div>
    </div>
  );
}

const DifficultyDot: React.FC<{ difficulty: string }> = ({ difficulty }) => (
  <span className={`practice-difficulty-dot practice-difficulty-dot--${difficulty}`}>
    {difficulty}
  </span>
);
