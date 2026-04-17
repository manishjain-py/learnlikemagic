import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  listRecentPracticeAttempts, retryPracticeGrading,
  PracticeAttemptSummary,
} from '../../api';

const POLL_INTERVAL_MS = 30_000;

/**
 * Floating top banner that surfaces graded / grading_failed practice
 * attempts not yet viewed. Polls `/practice/attempts/recent` every 30s.
 * Pauses polling when the tab is hidden to save battery (FR-35, FR-40).
 *
 * Clicking the banner navigates to the results page — the results page
 * calls `mark-viewed` on mount, which removes the attempt from the
 * `/recent` response on the next poll.
 *
 * Rendered inside AuthenticatedLayout so it sits above both AppShell
 * routes and chat-session routes.
 */
export default function PracticeBanner() {
  const navigate = useNavigate();
  const location = useLocation();
  const [attempts, setAttempts] = useState<PracticeAttemptSummary[]>([]);
  const [retrying, setRetrying] = useState<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // If the student is already on the results page for one of the recent
  // attempts, don't also surface a banner for it — the page itself shows
  // the score. mark-viewed fires on that page's mount, so the next poll
  // clears it anyway; this just avoids a noisy 30s overlap.
  const currentResultsId = location.pathname.match(
    /^\/practice\/attempts\/([^/]+)\/results/,
  )?.[1];

  const fetchRecent = useCallback(async () => {
    try {
      const res = await listRecentPracticeAttempts();
      setAttempts(res.attempts ?? []);
    } catch {
      // Silent fail — the banner is non-critical.
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    fetchRecent();
    pollRef.current = setInterval(fetchRecent, POLL_INTERVAL_MS);
  }, [fetchRecent]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (document.visibilityState === 'visible') startPolling();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') startPolling();
      else stopPolling();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  const handleRetry = async (attemptId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRetrying(prev => new Set(prev).add(attemptId));
    try {
      await retryPracticeGrading(attemptId);
      // Optimistic removal — next poll will confirm. If retry bounces the
      // attempt back to `grading_failed`, the banner will re-appear.
      setAttempts(prev => prev.filter(a => a.id !== attemptId));
    } catch {
      setRetrying(prev => { const n = new Set(prev); n.delete(attemptId); return n; });
    }
  };

  const visible = attempts.filter(a => a.id !== currentResultsId);
  if (visible.length === 0) return null;

  return (
    <div className="practice-banner-wrap">
      {visible.map(a => (
        <div
          key={a.id}
          className={`practice-banner practice-banner--${a.status === 'graded' ? 'graded' : 'failed'}`}
          onClick={() => navigate(`/practice/attempts/${a.id}/results`)}
          role="button"
          tabIndex={0}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') navigate(`/practice/attempts/${a.id}/results`); }}
        >
          <span className="practice-banner-icon" aria-hidden>
            {a.status === 'graded' ? '✓' : '!'}
          </span>
          <span className="practice-banner-text">
            {a.status === 'graded'
              ? <>Your practice set is ready — <strong>{a.total_score ?? '—'}/{a.total_possible}</strong></>
              : <>Grading didn't finish for your last practice set.</>}
          </span>
          {a.status === 'grading_failed' ? (
            <button
              className="practice-banner-retry"
              onClick={e => handleRetry(a.id, e)}
              disabled={retrying.has(a.id)}
            >
              {retrying.has(a.id) ? 'Retrying…' : 'Retry'}
            </button>
          ) : (
            <span className="practice-banner-arrow" aria-hidden>→</span>
          )}
        </div>
      ))}
    </div>
  );
}
