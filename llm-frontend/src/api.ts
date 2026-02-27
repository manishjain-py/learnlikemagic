/**
 * API client for Adaptive Tutor backend.
 *
 * All authenticated requests include the access token via Authorization header.
 * On 401 responses, redirects to /login.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Token storage — set by AuthContext after login
let _accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  _accessToken = token;
}

export function getAccessToken(): string | null {
  return _accessToken;
}

/**
 * Wrapper around fetch that adds auth headers and handles 401s.
 */
async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (_accessToken) {
    headers['Authorization'] = `Bearer ${_accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Token expired or invalid — redirect to login
    window.location.href = '/login';
    throw new Error('Authentication required');
  }

  return response;
}

// ──────────────────────────────────────────────
// Existing interfaces (unchanged)
// ──────────────────────────────────────────────

export interface Student {
  id: string;
  grade: number;
  prefs?: {
    style?: 'simple' | 'standard' | 'challenge';
    lang?: 'en' | 'hi';
  };
}

export interface Goal {
  topic: string;
  syllabus: string;
  learning_objectives: string[];
  guideline_id: string;
}

export interface CreateSessionRequest {
  student: Student;
  goal: Goal;
  mode?: 'teach_me' | 'clarify_doubts' | 'exam';
}

export interface Turn {
  message: string;
  hints: string[];
  step_idx: number;
  mastery_score: number;
  is_complete?: boolean;
  concepts_discussed?: string[];
  exam_progress?: {
    current_question: number;
    total_questions: number;
    answered_questions: number;
  };
  exam_feedback?: {
    score: number;
    total: number;
    percentage: number;
    strengths: string[];
    weak_areas: string[];
    patterns: string[];
    next_steps: string[];
  };
  exam_results?: Array<{
    question_idx: number;
    question_text: string;
    student_answer?: string | null;
    result?: 'correct' | 'partial' | 'incorrect' | null;
    score?: number;
    marks_rationale?: string;
    feedback?: string;
    expected_answer?: string;
  }>;
  exam_questions?: Array<{ question_idx: number; question_text: string }>;
}

export interface CreateSessionResponse {
  session_id: string;
  first_turn: Turn;
  mode?: string;
  past_discussions?: Array<{ session_date: string; concepts_discussed: string[] }>;
}

export interface StepResponse {
  next_turn: Turn;
  routing: string;
  last_grading?: {
    score: number;
    rationale: string;
    labels: string[];
    confidence: number;
  };
}

export interface SummaryResponse {
  steps_completed: number;
  mastery_score: number;
  misconceptions_seen: string[];
  suggestions: string[];
}

export interface SubtopicInfo {
  subtopic: string;
  guideline_id: string;
}

export interface CurriculumResponse {
  subjects?: string[];
  topics?: string[];
  subtopics?: SubtopicInfo[];
}

// ──────────────────────────────────────────────
// API functions (updated to use apiFetch)
// ──────────────────────────────────────────────

export async function getCurriculum(params: {
  country: string;
  board: string;
  grade: number;
  subject?: string;
  topic?: string;
}): Promise<CurriculumResponse> {
  const queryParams = new URLSearchParams({
    country: params.country,
    board: params.board,
    grade: params.grade.toString(),
    ...(params.subject && { subject: params.subject }),
    ...(params.topic && { topic: params.topic }),
  });

  const response = await apiFetch(`/curriculum?${queryParams}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch curriculum: ${response.statusText}`);
  }

  return response.json();
}

export class SessionConflictError extends Error {
  existing_session_id: string;
  constructor(message: string, existingSessionId: string) {
    super(message);
    this.name = 'SessionConflictError';
    this.existing_session_id = existingSessionId;
  }
}

export async function createSession(
  request: CreateSessionRequest
): Promise<CreateSessionResponse> {
  const response = await apiFetch('/sessions', {
    method: 'POST',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      // 409 with existing_session_id → throw structured error for resume redirect
      if (response.status === 409 && body?.detail?.existing_session_id) {
        throw new SessionConflictError(
          body.detail.message || 'Session conflict',
          body.detail.existing_session_id,
        );
      }
      message = body?.detail?.message || body?.detail || message;
    } catch (e) {
      if (e instanceof SessionConflictError) throw e;
      /* use statusText */
    }
    throw new Error(message);
  }

  return response.json();
}

export async function submitStep(
  sessionId: string,
  studentReply: string
): Promise<StepResponse> {
  const response = await apiFetch(`/sessions/${sessionId}/step`, {
    method: 'POST',
    body: JSON.stringify({ student_reply: studentReply }),
  });

  if (!response.ok) {
    throw new Error(`Failed to submit step: ${response.statusText}`);
  }

  return response.json();
}

export interface ModelConfigEntry {
  provider: string;
  model_id: string;
  description: string;
}

export type ModelConfig = Record<string, ModelConfigEntry>;

export async function getModelConfig(): Promise<ModelConfig> {
  const response = await apiFetch('/config/models');
  if (!response.ok) {
    throw new Error(`Failed to fetch model config: ${response.statusText}`);
  }
  return response.json();
}

export async function getSummary(sessionId: string): Promise<SummaryResponse> {
  const response = await apiFetch(`/sessions/${sessionId}/summary`);

  if (!response.ok) {
    throw new Error(`Failed to get summary: ${response.statusText}`);
  }

  return response.json();
}

// ──────────────────────────────────────────────
// Report Card types & API
// ──────────────────────────────────────────────

export interface ReportCardSubtopic {
  subtopic: string;
  subtopic_key: string;
  guideline_id: string | null;
  coverage: number;
  latest_exam_score: number | null;
  latest_exam_total: number | null;
  last_studied: string | null;
}

export interface ReportCardTopic {
  topic: string;
  topic_key: string;
  subtopics: ReportCardSubtopic[];
}

export interface ReportCardSubject {
  subject: string;
  topics: ReportCardTopic[];
}

export interface ReportCardResponse {
  total_sessions: number;
  total_topics_studied: number;
  subjects: ReportCardSubject[];
}

export interface SubtopicProgress {
  coverage: number;
  session_count: number;
  status: 'studied' | 'not_started';
}

export interface ResumableSession {
  session_id: string;
  coverage: number;
  current_step: number;
  total_steps: number;
  concepts_covered: string[];
}

export interface PauseSummary {
  coverage: number;
  concepts_covered: string[];
  message: string;
}

export interface ExamSummary {
  score: number;
  total: number;
  percentage: number;
  feedback?: {
    strengths: string[];
    weak_areas: string[];
    patterns: string[];
    next_steps: string[];
  };
}

export async function getReportCard(): Promise<ReportCardResponse> {
  const response = await apiFetch('/sessions/report-card');
  if (!response.ok) throw new Error(`Failed to fetch report card: ${response.statusText}`);
  return response.json();
}

export async function getSubtopicProgress(): Promise<Record<string, SubtopicProgress>> {
  const response = await apiFetch('/sessions/subtopic-progress');
  if (!response.ok) throw new Error(`Failed to fetch progress: ${response.statusText}`);
  const data = await response.json();
  return data.user_progress;
}

export async function getResumableSession(guidelineId: string): Promise<ResumableSession | null> {
  const response = await apiFetch(`/sessions/resumable?guideline_id=${guidelineId}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Failed to check resumable session: ${response.statusText}`);
  return response.json();
}

export async function pauseSession(sessionId: string): Promise<PauseSummary> {
  const response = await apiFetch(`/sessions/${sessionId}/pause`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to pause session: ${response.statusText}`);
  return response.json();
}

export async function resumeSession(sessionId: string): Promise<{ session_id: string; message: string; current_step: number }> {
  const response = await apiFetch(`/sessions/${sessionId}/resume`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to resume session: ${response.statusText}`);
  return response.json();
}

export async function endClarifySession(sessionId: string): Promise<{ concepts_discussed: string[]; message: string }> {
  const response = await apiFetch(`/sessions/${sessionId}/end-clarify`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to end clarify session: ${response.statusText}`);
  return response.json();
}

export async function endExamEarly(sessionId: string): Promise<ExamSummary> {
  const response = await apiFetch(`/sessions/${sessionId}/end-exam`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to end exam: ${response.statusText}`);
  return response.json();
}

export async function getSessionReplay(sessionId: string): Promise<any> {
  const response = await apiFetch(`/sessions/${sessionId}/replay`);
  if (!response.ok) throw new Error(`Failed to fetch session replay: ${response.statusText}`);
  return response.json();
}

// ──────────────────────────────────────────────
// Guideline sessions & exam review
// ──────────────────────────────────────────────

export interface GuidelineSessionEntry {
  session_id: string;
  mode: string;
  created_at: string | null;
  is_complete: boolean;
  exam_finished: boolean;
  exam_score: number | null;
  exam_total: number | null;
  exam_answered: number | null;
  coverage: number | null;
}

export interface ExamReviewQuestion {
  question_idx: number;
  question_text: string;
  student_answer: string | null;
  expected_answer: string;
  result: string | null;
  score: number;
  marks_rationale: string;
  feedback: string;
  concept: string;
  difficulty: string;
}

export interface ExamReviewResponse {
  session_id: string;
  created_at: string | null;
  exam_feedback: { score: number; total: number; percentage: number; strengths?: string[]; weak_areas?: string[]; patterns?: string[]; next_steps?: string[] } | null;
  questions: ExamReviewQuestion[];
}

export async function getGuidelineSessions(
  guidelineId: string,
  mode?: string,
  finishedOnly?: boolean,
): Promise<GuidelineSessionEntry[]> {
  const params = new URLSearchParams();
  if (mode) params.set('mode', mode);
  if (finishedOnly) params.set('finished_only', 'true');
  const qs = params.toString();
  const response = await apiFetch(`/sessions/guideline/${guidelineId}${qs ? `?${qs}` : ''}`);
  if (!response.ok) throw new Error(`Failed to fetch guideline sessions: ${response.statusText}`);
  const data = await response.json();
  return data.sessions;
}

export async function getExamReview(sessionId: string): Promise<ExamReviewResponse> {
  const response = await apiFetch(`/sessions/${sessionId}/exam-review`);
  if (!response.ok) throw new Error(`Failed to fetch exam review: ${response.statusText}`);
  return response.json();
}

// ──────────────────────────────────────────────
// Audio transcription
// ──────────────────────────────────────────────

export async function transcribeAudio(audioBlob: Blob): Promise<string> {
  // Derive file extension from the blob's actual MIME type
  const extMap: Record<string, string> = {
    'audio/webm': 'webm', 'audio/mp4': 'mp4', 'audio/ogg': 'ogg',
    'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'audio/flac': 'flac',
  };
  const ext = extMap[audioBlob.type] || 'webm';

  const formData = new FormData();
  formData.append('file', audioBlob, `recording.${ext}`);

  // Can't use apiFetch here — it forces Content-Type: application/json.
  // FormData needs the browser to set multipart/form-data with boundary.
  const headers: Record<string, string> = {};
  if (_accessToken) {
    headers['Authorization'] = `Bearer ${_accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}/transcribe`, {
    method: 'POST',
    headers,
    body: formData,
  });

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Authentication required');
  }

  if (!response.ok) {
    throw new Error(`Transcription failed: ${response.statusText}`);
  }

  const data = await response.json();
  return data.text;
}
