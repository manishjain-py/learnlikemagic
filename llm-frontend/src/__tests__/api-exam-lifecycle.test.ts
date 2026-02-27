/**
 * Tests for exam lifecycle API functions.
 *
 * Covers:
 * - createSession 409 conflict returns SessionConflictError with existing_session_id
 * - getExamReview returns proper data
 * - getGuidelineSessions returns sessions list
 */
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Must import AFTER mocking fetch
import {
  createSession,
  SessionConflictError,
  getExamReview,
  getGuidelineSessions,
  setAccessToken,
} from '../api';

beforeEach(() => {
  mockFetch.mockClear();
  setAccessToken('test-token');
});


describe('createSession 409 conflict handling', () => {
  it('throws SessionConflictError with existing_session_id on 409', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({
        detail: {
          message: 'An incomplete exam already exists for this topic',
          existing_session_id: 'existing-exam-42',
        },
      }),
    });

    const request = {
      student: { id: 's1', grade: 3 },
      goal: {
        topic: 'Fractions',
        syllabus: 'CBSE',
        learning_objectives: ['Test'],
        guideline_id: 'g1',
      },
      mode: 'exam' as const,
    };

    try {
      await createSession(request);
      expect.fail('Should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(SessionConflictError);
      expect((e as SessionConflictError).existing_session_id).toBe('existing-exam-42');
      expect((e as SessionConflictError).message).toContain('incomplete exam');
    }
  });

  it('throws generic Error on non-409 errors', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({
        detail: { message: 'Something went wrong' },
      }),
    });

    const request = {
      student: { id: 's1', grade: 3 },
      goal: {
        topic: 'Fractions',
        syllabus: 'CBSE',
        learning_objectives: ['Test'],
        guideline_id: 'g1',
      },
      mode: 'exam' as const,
    };

    await expect(createSession(request)).rejects.toThrow(Error);
    await expect(createSession(request)).rejects.not.toThrow(SessionConflictError);
  });

  it('returns session on success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 'new-session-1',
        first_turn: { message: 'Welcome!', hints: [], step_idx: 1 },
        mode: 'teach_me',
      }),
    });

    const request = {
      student: { id: 's1', grade: 3 },
      goal: {
        topic: 'Fractions',
        syllabus: 'CBSE',
        learning_objectives: ['Learn'],
        guideline_id: 'g1',
      },
    };

    const result = await createSession(request);
    expect(result.session_id).toBe('new-session-1');
  });
});


describe('getExamReview', () => {
  it('returns exam review data for finished exam', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        session_id: 'exam-1',
        created_at: '2026-02-27T10:00:00',
        exam_feedback: { score: 2.5, total: 3, percentage: 83.3 },
        questions: [
          {
            question_idx: 0,
            question_text: 'What is 1/2?',
            student_answer: 'Half',
            expected_answer: 'One half',
            result: 'correct',
            score: 1.0,
            marks_rationale: 'Good answer',
            feedback: '',
            concept: 'Fractions',
            difficulty: 'easy',
          },
        ],
      }),
    });

    const result = await getExamReview('exam-1');
    expect(result.session_id).toBe('exam-1');
    expect(result.questions).toHaveLength(1);
    expect(result.questions[0].score).toBe(1.0);
  });

  it('throws on error response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: 'Forbidden',
    });

    await expect(getExamReview('unfinished-exam')).rejects.toThrow();
  });
});


describe('getGuidelineSessions', () => {
  it('returns sessions list', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        sessions: [
          {
            session_id: 's1',
            mode: 'exam',
            created_at: '2026-02-27T10:00:00',
            is_complete: true,
            exam_finished: true,
            exam_score: 2.5,
            exam_total: 3,
            exam_answered: 3,
            coverage: null,
          },
        ],
      }),
    });

    const result = await getGuidelineSessions('g1');
    expect(result).toHaveLength(1);
    expect(result[0].session_id).toBe('s1');
    expect(result[0].exam_score).toBe(2.5);
  });

  it('passes mode and finished_only query params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ sessions: [] }),
    });

    await getGuidelineSessions('g1', 'exam', true);

    const calledUrl = mockFetch.mock.calls[0][0] as string;
    expect(calledUrl).toContain('mode=exam');
    expect(calledUrl).toContain('finished_only=true');
  });
});
