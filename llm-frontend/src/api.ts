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
}

export interface Turn {
  message: string;
  hints: string[];
  step_idx: number;
  mastery_score: number;
  is_complete?: boolean;
}

export interface CreateSessionResponse {
  session_id: string;
  first_turn: Turn;
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

export async function createSession(
  request: CreateSessionRequest
): Promise<CreateSessionResponse> {
  const response = await apiFetch('/sessions', {
    method: 'POST',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Failed to create session: ${response.statusText}`);
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

export interface ModelConfig {
  tutor: { provider: string; model_label: string };
  ingestion: { provider: string; model_label: string };
}

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
