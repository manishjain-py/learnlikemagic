import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import QuestionRenderer from '../components/practice/QuestionRenderer';
import {
  getPracticeAttempt, markPracticeViewed, retryPracticeGrading, startPractice,
  PracticeAttempt, PracticeAttemptResults, GradedQuestion,
} from '../api';

const POLL_INTERVAL_MS = 2000;
// Stop polling after ~5 minutes. A grading worker that's still running past
// this mark is almost certainly dead (silent thread death is an acknowledged
// v1 limitation). Surface a stuck-grading state + Retry instead of polling
// forever. Tracks with the post-v1 server-side sweeper plan.
const POLL_MAX_ATTEMPTS = 150; // 150 * 2s = 5 min

interface PracticeFlowState {
  topicTitle?: string;
  subject?: string;
  chapter?: string;
  topic?: string;
  topicKey?: string | null;
}

/**
 * Results + review of one attempt. Drives three states:
 *   - grading: spinner + 2s poll until the worker finishes
 *   - graded: score summary + per-question review with rationales
 *   - grading_failed: retry button
 * If status is in_progress on load, redirect to the runner.
 */
export default function PracticeResultsPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const flowState = (location.state as PracticeFlowState | null) ?? {};
  const topicTitle = flowState.topicTitle;
  const canReteach = Boolean(flowState.subject && flowState.chapter && flowState.topic);

  const [attempt, setAttempt] = useState<PracticeAttempt | PracticeAttemptResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [practiceAgainLoading, setPracticeAgainLoading] = useState(false);
  const [pollStuck, setPollStuck] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const viewedMarkedRef = useRef(false);

  useEffect(() => {
    if (!attemptId) return;
    (async () => {
      try {
        const a = await getPracticeAttempt(attemptId);
        if (a.status === 'in_progress') {
          navigate(`/practice/attempts/${attemptId}/run`,
            { replace: true, state: flowState });
          return;
        }
        setAttempt(a);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [attemptId, navigate, topicTitle]);

  useEffect(() => {
    if (!attemptId || !attempt) return;
    if (attempt.status !== 'grading') return;
    pollCountRef.current = 0;
    pollRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > POLL_MAX_ATTEMPTS) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        setPollStuck(true);
        return;
      }
      try {
        const a = await getPracticeAttempt(attemptId);
        setAttempt(a);
        if (a.status !== 'grading' && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch { /* ignore */ }
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [attemptId, attempt]);

  useEffect(() => {
    if (!attemptId || !attempt) return;
    if (attempt.status !== 'graded' && attempt.status !== 'grading_failed') return;
    if (viewedMarkedRef.current) return;
    viewedMarkedRef.current = true;
    markPracticeViewed(attemptId).catch(() => {});
  }, [attemptId, attempt]);

  const handleRetry = async () => {
    if (!attemptId) return;
    setRetrying(true);
    setError(null);
    setPollStuck(false);
    pollCountRef.current = 0;
    try {
      await retryPracticeGrading(attemptId);
      setAttempt(prev => prev ? { ...prev, status: 'grading' } as any : prev);
      setRetrying(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRetrying(false);
    }
  };

  const handleReteach = () => {
    if (!canReteach || !attempt) return;
    const url = `/learn/${encodeURIComponent(flowState.subject!)}/${encodeURIComponent(flowState.chapter!)}/${encodeURIComponent(flowState.topic!)}?autostart=teach_me`;
    navigate(url, {
      state: {
        topicKey: flowState.topicKey,
        guidelineId: attempt.guideline_id,
      },
    });
  };

  const handlePracticeAgain = async () => {
    if (!attempt) return;
    setPracticeAgainLoading(true);
    try {
      const fresh = await startPractice(attempt.guideline_id);
      navigate(`/practice/attempts/${fresh.id}/run`, { state: flowState });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPracticeAgainLoading(false);
    }
  };

  if (loading) {
    return <div className="app-content-inner"><p className="page-loading">Loading…</p></div>;
  }
  if (!attempt) {
    return (
      <div className="selection-step">
        <div className="practice-error">{error || 'Attempt not found.'}</div>
      </div>
    );
  }

  if (attempt.status === 'grading') {
    if (pollStuck) {
      return (
        <div className="selection-step">
          {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
          <h2>Grading is taking longer than expected</h2>
          <div className="practice-error">
            We haven't heard back from the grader in a while. Tap Retry to
            spin up a fresh grading run.
          </div>
          {error && <div className="practice-error">{error}</div>}
          <button
            className="practice-retry-btn"
            onClick={handleRetry}
            disabled={retrying}
          >
            {retrying ? 'Retrying…' : 'Retry grading'}
          </button>
        </div>
      );
    }
    return (
      <div className="selection-step">
        {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
        <h2>Grading your answers…</h2>
        <div className="practice-grading-wrap">
          <div className="practice-grading-note">This usually takes a few seconds.</div>
        </div>
      </div>
    );
  }

  if (attempt.status === 'grading_failed') {
    const results = attempt as PracticeAttemptResults;
    return (
      <div className="selection-step">
        {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
        <h2>Grading didn't finish</h2>
        <div className="practice-error">
          {results.grading_error || 'The grading worker ran into an error. Try again below.'}
        </div>
        {error && <div className="practice-error">{error}</div>}
        <button
          className="practice-retry-btn"
          onClick={handleRetry}
          disabled={retrying}
        >
          {retrying ? 'Retrying…' : 'Retry grading'}
        </button>
      </div>
    );
  }

  const results = attempt as PracticeAttemptResults;
  const scoreText = results.total_score !== null
    ? `${results.total_score}/${results.total_possible}`
    : '—';
  const correctCount = results.questions.filter(q => q.correct).length;

  return (
    <div className="selection-step">
      {topicTitle && <div className="practice-header-topic">{topicTitle}</div>}
      <h2>Your score</h2>

      <div className="practice-score-card">
        <div className="practice-score-badge">{scoreText}</div>
        <div style={{ flex: 1 }}>
          <div className="practice-score-label">
            {correctCount}/{results.questions.length} correct
          </div>
          <div className="practice-score-sub">
            Tap any question below to see why.
          </div>
        </div>
      </div>

      <div className="practice-cta-row">
        <button
          className="practice-nav-btn practice-nav-btn--primary"
          onClick={handlePracticeAgain}
          disabled={practiceAgainLoading}
        >
          {practiceAgainLoading ? 'Starting…' : 'Practice again'}
        </button>
        {canReteach && (
          <button
            className="practice-nav-btn practice-nav-btn--ghost"
            onClick={handleReteach}
          >
            Reteach this topic
          </button>
        )}
        <button
          className="practice-nav-btn practice-nav-btn--ghost"
          onClick={() => navigate(`/practice/${results.guideline_id}`, { state: flowState })}
        >
          Back to topic
        </button>
      </div>

      {results.questions.map((gq, idx) => (
        <ReviewRow key={gq.q_idx} gq={gq} idx={idx} />
      ))}
    </div>
  );
}

const ReviewRow: React.FC<{ gq: GradedQuestion; idx: number }> = ({ gq, idx }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="practice-review-row">
      <button className="practice-review-btn" onClick={() => setOpen(o => !o)}>
        <span className={`practice-review-tick ${gq.correct ? 'correct' : 'wrong'}`}>
          {gq.correct ? '✓' : '✗'}
        </span>
        <span className="practice-review-text">
          {(gq.question_json.question_text as string) || '(no question text)'}
        </span>
        <span className="practice-review-meta">
          Q{idx + 1} · {gq.score.toFixed(1)}
        </span>
      </button>
      {open && (
        <div className="practice-review-expand">
          <QuestionRenderer
            format={gq.format}
            questionJson={gq.question_json}
            value={gq.student_answer ?? null}
            onChange={() => {}}
            seed={0}
            disabled
          />
          {gq.rationale && (
            <div className={`practice-review-rationale practice-review-rationale--${gq.correct ? 'correct' : 'wrong'}`}>
              {gq.rationale}
            </div>
          )}
          {gq.correct_answer_summary !== undefined && gq.correct_answer_summary !== null && !gq.correct && (
            <div className="practice-review-correct-answer">
              <strong>Correct answer: </strong>
              {typeof gq.correct_answer_summary === 'string'
                ? gq.correct_answer_summary
                : JSON.stringify(gq.correct_answer_summary)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
