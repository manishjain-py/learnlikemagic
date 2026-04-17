import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import {
  getPracticeAvailability, listPracticeAttemptsForTopic, startPractice,
  PracticeAvailability, PracticeAttemptSummary,
} from '../api';

/**
 * Practice topic entry page. Shows availability + past attempts + a
 * "Start Practice" button. Minimal v1 — Step 10's ModeSelectPage refactor
 * will likely fold this into the mode tile later.
 */
interface PracticeFlowState {
  topicTitle?: string;
  subject?: string;
  chapter?: string;
  topic?: string;
  topicKey?: string | null;
}

export default function PracticeLandingPage() {
  const { guidelineId } = useParams<{ guidelineId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const flowState = (location.state as PracticeFlowState | null) ?? {};
  const topicTitle = flowState.topicTitle ?? 'Practice Set';
  const forwardState: PracticeFlowState = {
    topicTitle: flowState.topicTitle,
    subject: flowState.subject,
    chapter: flowState.chapter,
    topic: flowState.topic,
    topicKey: flowState.topicKey,
  };

  const [availability, setAvailability] = useState<PracticeAvailability | null>(null);
  const [history, setHistory] = useState<PracticeAttemptSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guidelineId) return;
    Promise.all([
      getPracticeAvailability(guidelineId),
      listPracticeAttemptsForTopic(guidelineId),
    ])
      .then(([avail, hist]) => {
        setAvailability(avail);
        setHistory(hist);
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [guidelineId]);

  const handleStart = async () => {
    if (!guidelineId) return;
    setStarting(true);
    setError(null);
    try {
      const attempt = await startPractice(guidelineId);
      const route = attempt.status === 'in_progress'
        ? `/practice/attempts/${attempt.id}/run`
        : `/practice/attempts/${attempt.id}/results`;
      navigate(route, { state: forwardState });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStarting(false);
    }
  };

  if (loading) {
    return <div className="app-content-inner"><p className="page-loading">Loading...</p></div>;
  }

  return (
    <div className="selection-step">
      <button className="back-button" onClick={() => navigate(-1)}>← Back</button>

      <h2>Let's Practice</h2>
      <p className="mode-desc">{topicTitle}</p>

      {error && <div className="practice-error">{error}</div>}

      {availability?.available ? (
        <button
          onClick={handleStart}
          disabled={starting}
          className="practice-start-btn"
        >
          {starting ? 'Starting…' : 'Start a 10-question set'}
        </button>
      ) : (
        <div className="practice-unavailable-banner">
          No practice bank available for this topic yet
          {availability ? ` (${availability.question_count} questions; need 10)` : ''}.
        </div>
      )}

      {history.length > 0 && (
        <>
          <div className="practice-history-title">Past attempts</div>
          <div className="practice-history-list">
            {history.map(a => (
              <button
                key={a.id}
                className="practice-history-row"
                onClick={() => navigate(`/practice/attempts/${a.id}/results`, { state: forwardState })}
                disabled={a.status === 'in_progress' || a.status === 'grading'}
              >
                <StatusChip status={a.status} />
                <span className="practice-history-date">
                  {a.graded_at
                    ? new Date(a.graded_at).toLocaleString()
                    : a.submitted_at
                      ? new Date(a.submitted_at).toLocaleString()
                      : 'in progress'}
                </span>
                {a.total_score !== null && (
                  <span className="practice-history-score">
                    {a.total_score}/{a.total_possible}
                  </span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

const CHIP_CLASS: Record<string, string> = {
  in_progress:    'practice-chip practice-chip--inprogress',
  grading:        'practice-chip practice-chip--grading',
  graded:         'practice-chip practice-chip--graded',
  grading_failed: 'practice-chip practice-chip--failed',
};
const CHIP_LABEL: Record<string, string> = {
  in_progress: 'In progress',
  grading: 'Grading',
  graded: 'Graded',
  grading_failed: 'Failed',
};

const StatusChip: React.FC<{ status: string }> = ({ status }) => (
  <span className={CHIP_CLASS[status] || 'practice-chip'}>
    {CHIP_LABEL[status] || status}
  </span>
);
