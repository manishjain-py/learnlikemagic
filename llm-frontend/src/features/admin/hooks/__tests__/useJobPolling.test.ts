/**
 * Tests for useJobPolling hook.
 *
 * Covers test matrix Category 5: Frontend Polling Lifecycle (5.1-5.4).
 *
 * Strategy: Use vi.useFakeTimers({ shouldAdvanceTime: true }) so that
 * fake timers coexist with real async resolution. This lets us control
 * setInterval while still awaiting Promise resolution.
 */
import { renderHook, act, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { useJobPolling } from '../useJobPolling';

// Mock the API module
vi.mock('../../api/adminApi', () => ({
  getLatestJob: vi.fn(),
  getJobStatus: vi.fn(),
}));

import { getLatestJob, getJobStatus } from '../../api/adminApi';

const mockGetLatestJob = vi.mocked(getLatestJob);
const mockGetJobStatus = vi.mocked(getJobStatus);

function makeJob(overrides: Record<string, unknown> = {}) {
  return {
    job_id: 'job-123',
    book_id: 'book-1',
    job_type: 'extraction',
    status: 'running' as const,
    total_items: 10,
    completed_items: 3,
    failed_items: 0,
    current_item: 4,
    last_completed_item: 3,
    progress_detail: null,
    heartbeat_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: null,
    error_message: null,
    ...overrides,
  };
}

// Flush microtasks (Promise resolution) manually
const flushPromises = () => new Promise(resolve => setTimeout(resolve, 0));

describe('useJobPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockGetLatestJob.mockReset();
    mockGetJobStatus.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('5.1: Detects running job on mount', () => {
    it('fetches getLatestJob on mount and starts polling if running', async () => {
      const runningJob = makeJob({ status: 'running' });
      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus.mockResolvedValue(runningJob);

      const { result } = renderHook(() => useJobPolling('book-1', 'extraction'));

      // Let the useEffect's async checkActiveJob resolve
      await act(async () => {
        await flushPromises();
      });

      expect(mockGetLatestJob).toHaveBeenCalledWith('book-1', 'extraction');
      expect(result.current.job).not.toBeNull();
      expect(result.current.job?.status).toBe('running');
      expect(result.current.isPolling).toBe(true);
    });

    it('sets job but does not poll if job is completed on mount', async () => {
      const completedJob = makeJob({ status: 'completed' });
      mockGetLatestJob.mockResolvedValue(completedJob);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('completed');
      expect(result.current.isPolling).toBe(false);
    });

    it('handles null (no jobs) on mount', async () => {
      mockGetLatestJob.mockResolvedValue(null);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.job).toBeNull();
      expect(result.current.isPolling).toBe(false);
    });
  });

  describe('5.2: Polling stops on completion', () => {
    it('stops polling when job status becomes completed', async () => {
      const runningJob = makeJob({ status: 'running' });
      const completedJob = makeJob({ status: 'completed', completed_items: 10 });

      mockGetLatestJob.mockResolvedValue(runningJob);
      // startPolling(job_id) calls getJobStatus:
      // 1st: immediate poll (running), 2nd: interval poll (completed)
      mockGetJobStatus
        .mockResolvedValueOnce(runningJob)
        .mockResolvedValueOnce(completedJob);

      const { result } = renderHook(() => useJobPolling('book-1', 'extraction'));

      // Mount: checkActiveJob detects running → startPolling
      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);

      // Advance past the 3s interval to trigger next poll
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('completed');
      expect(result.current.isPolling).toBe(false);
    });

    it('stops polling when job status becomes failed', async () => {
      const runningJob = makeJob({ status: 'running' });
      const failedJob = makeJob({ status: 'failed', error_message: 'timeout' });

      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus
        .mockResolvedValueOnce(runningJob)
        .mockResolvedValueOnce(failedJob);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);

      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('failed');
      expect(result.current.isPolling).toBe(false);
    });
  });

  describe('5.3: Cleanup on unmount', () => {
    it('clears interval on unmount', async () => {
      const clearIntervalSpy = vi.spyOn(global, 'clearInterval');
      const runningJob = makeJob({ status: 'running' });

      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus.mockResolvedValue(runningJob);

      const { result, unmount } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);

      unmount();

      // stopPolling is called (which calls clearInterval)
      expect(clearIntervalSpy).toHaveBeenCalled();
      clearIntervalSpy.mockRestore();
    });
  });

  describe('5.4: Multiple mount/unmount cycles', () => {
    it('starts fresh polling on each mount', async () => {
      const runningJob = makeJob({ status: 'running' });
      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus.mockResolvedValue(runningJob);

      // First mount
      const { result: result1, unmount: unmount1 } = renderHook(() =>
        useJobPolling('book-1')
      );

      await act(async () => {
        await flushPromises();
      });

      expect(result1.current.isPolling).toBe(true);
      unmount1();

      // Second mount
      mockGetLatestJob.mockClear();
      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus.mockClear();
      mockGetJobStatus.mockResolvedValue(runningJob);

      const { result: result2 } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result2.current.isPolling).toBe(true);
      expect(mockGetLatestJob).toHaveBeenCalled();
    });
  });

  describe('startPolling and stopPolling controls', () => {
    it('startPolling with jobId polls getJobStatus', async () => {
      const job = makeJob({ status: 'running' });
      mockGetLatestJob.mockResolvedValue(null); // no active job on mount
      mockGetJobStatus.mockResolvedValue(job);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(false);

      // Manually start polling with specific job ID
      await act(async () => {
        result.current.startPolling('job-123');
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);
      expect(mockGetJobStatus).toHaveBeenCalledWith('book-1', 'job-123');
    });

    it('stopPolling stops active polling', async () => {
      const runningJob = makeJob({ status: 'running' });
      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus.mockResolvedValue(runningJob);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);

      act(() => {
        result.current.stopPolling();
      });

      expect(result.current.isPolling).toBe(false);
    });
  });

  describe('Error handling', () => {
    it('silently handles API errors during polling', async () => {
      const runningJob = makeJob({ status: 'running' });
      mockGetLatestJob.mockResolvedValue(runningJob);
      mockGetJobStatus
        .mockResolvedValueOnce(runningJob) // initial poll succeeds
        .mockRejectedValueOnce(new Error('Network error')) // error on 2nd
        .mockResolvedValueOnce(runningJob); // 3rd recovers

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.isPolling).toBe(true);

      // 2nd poll: error
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      // Should still be polling (error didn't crash)
      expect(result.current.isPolling).toBe(true);

      // 3rd poll: recovers
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('running');
    });

    it('silently handles mount API error', async () => {
      mockGetLatestJob.mockRejectedValue(new Error('API unreachable'));

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.job).toBeNull();
      expect(result.current.isPolling).toBe(false);
    });
  });

  describe('Mixed success + intermittent failure patterns', () => {
    it('tracks progress through partial OCR failures', async () => {
      // Simulates: job running with 3/5 completed, 2 failed
      const partialJob = makeJob({
        status: 'running',
        total_items: 5,
        completed_items: 3,
        failed_items: 2,
        current_item: 5,
        progress_detail: JSON.stringify({
          page_errors: {
            '2': { error: 'Rate limit 429', error_type: 'retryable' },
            '4': { error: 'Rate limit 429', error_type: 'retryable' },
          },
        }),
      });

      const completedJob = makeJob({
        status: 'completed',
        total_items: 5,
        completed_items: 3,
        failed_items: 2,
        current_item: 5,
        progress_detail: partialJob.progress_detail,
      });

      mockGetLatestJob.mockResolvedValue(partialJob);
      mockGetJobStatus
        .mockResolvedValueOnce(partialJob)
        .mockResolvedValueOnce(completedJob);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      // While running, job reflects partial progress
      expect(result.current.job?.completed_items).toBe(3);
      expect(result.current.job?.failed_items).toBe(2);
      expect(result.current.isPolling).toBe(true);

      // Next poll: completed with same counts
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('completed');
      expect(result.current.job?.completed_items).toBe(3);
      expect(result.current.job?.failed_items).toBe(2);
      expect(result.current.isPolling).toBe(false);

      // Frontend can parse progress_detail for per-page errors
      const detail = JSON.parse(result.current.job!.progress_detail!);
      expect(detail.page_errors['2'].error_type).toBe('retryable');
      expect(detail.page_errors['4'].error_type).toBe('retryable');
    });

    it('handles job transitioning from 0 progress to completed', async () => {
      const freshJob = makeJob({
        status: 'running',
        completed_items: 0,
        failed_items: 0,
        current_item: 1,
      });

      const doneJob = makeJob({
        status: 'completed',
        completed_items: 10,
        failed_items: 0,
        current_item: 10,
      });

      mockGetLatestJob.mockResolvedValue(freshJob);
      mockGetJobStatus
        .mockResolvedValueOnce(freshJob)
        .mockResolvedValueOnce(doneJob);

      const { result } = renderHook(() => useJobPolling('book-1'));

      await act(async () => {
        await flushPromises();
      });

      expect(result.current.job?.completed_items).toBe(0);

      await act(async () => {
        vi.advanceTimersByTime(3100);
        await flushPromises();
      });

      expect(result.current.job?.status).toBe('completed');
      expect(result.current.job?.completed_items).toBe(10);
      expect(result.current.isPolling).toBe(false);
    });
  });
});
