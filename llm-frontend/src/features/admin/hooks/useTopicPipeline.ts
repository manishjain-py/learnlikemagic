/**
 * useTopicPipeline — fetch + smart-polling hook for the Topic Pipeline Dashboard.
 *
 * Polls `/pipeline` every 3s ONLY while any stage is running, stops cleanly
 * when all stages are settled. Handles unmount and visibility changes.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getTopicPipeline,
  TopicPipelineStatus,
} from '../api/adminApiV2';

const POLL_INTERVAL_MS = 3000;

interface UseTopicPipelineResult {
  data: TopicPipelineStatus | null;
  error: Error | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useTopicPipeline(
  bookId: string,
  chapterId: string,
  topicKey: string,
): UseTopicPipelineResult {
  const [data, setData] = useState<TopicPipelineStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const activeRef = useRef<boolean>(true);
  const timerRef = useRef<number | null>(null);

  const fetchOnce = useCallback(async (): Promise<TopicPipelineStatus | null> => {
    try {
      const next = await getTopicPipeline(bookId, chapterId, topicKey);
      if (!activeRef.current) return null;
      setData(next);
      setError(null);
      setLoading(false);
      return next;
    } catch (err) {
      if (!activeRef.current) return null;
      setError(err as Error);
      setLoading(false);
      return null;
    }
  }, [bookId, chapterId, topicKey]);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const tick = useCallback(async () => {
    if (!activeRef.current) return;
    const next = await fetchOnce();
    if (!activeRef.current) return;
    if (!next) return;
    const anyRunning = next.stages.some((s) => s.state === 'running');
    if (!anyRunning) return;
    timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
  }, [fetchOnce]);

  useEffect(() => {
    activeRef.current = true;
    setLoading(true);
    tick();

    const handleVisibility = () => {
      if (!document.hidden && activeRef.current) {
        clearTimer();
        tick();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      activeRef.current = false;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [tick, clearTimer]);

  const refresh = useCallback(async () => {
    clearTimer();
    await tick();
  }, [clearTimer, tick]);

  return { data, error, loading, refresh };
}
