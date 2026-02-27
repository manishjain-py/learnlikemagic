import { useState, useEffect, useRef, useCallback } from 'react';
import { getLatestJob, getJobStatus } from '../api/adminApi';
import { JobStatus } from '../types';

const POLL_INTERVAL_MS = 3000;

export function useJobPolling(bookId: string, jobType?: string) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    setIsPolling(false);
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback((jobId?: string) => {
    // Clear any existing interval first
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    setIsPolling(true);

    const poll = async () => {
      try {
        const result = jobId
          ? await getJobStatus(bookId, jobId)
          : await getLatestJob(bookId, jobType);

        setJob(result);

        // Stop polling when job completes or fails
        if (result && (result.status === 'completed' || result.status === 'failed')) {
          stopPolling();
        }
      } catch {
        // Silently handle polling errors
      }
    };

    // Poll immediately, then at interval
    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, [bookId, jobType, stopPolling]);

  // Check for active job on mount
  useEffect(() => {
    const checkActiveJob = async () => {
      try {
        const result = await getLatestJob(bookId, jobType);
        if (result && (result.status === 'running' || result.status === 'pending')) {
          setJob(result);
          startPolling(result.job_id);
        }
      } catch {
        // No active job
      }
    };
    checkActiveJob();

    return () => stopPolling();
  }, [bookId, jobType, startPolling, stopPolling]);

  return { job, isPolling, startPolling, stopPolling, setJob };
}
