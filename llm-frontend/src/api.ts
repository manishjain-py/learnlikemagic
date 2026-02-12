/**
 * API client for Adaptive Tutor backend
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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

  const response = await fetch(`${API_BASE_URL}/curriculum?${queryParams}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch curriculum: ${response.statusText}`);
  }

  return response.json();
}

export async function createSession(
  request: CreateSessionRequest
): Promise<CreateSessionResponse> {
  const response = await fetch(`${API_BASE_URL}/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
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
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/step`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
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
  const response = await fetch(`${API_BASE_URL}/config/models`);
  if (!response.ok) {
    throw new Error(`Failed to fetch model config: ${response.statusText}`);
  }
  return response.json();
}

export async function getSummary(sessionId: string): Promise<SummaryResponse> {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/summary`);

  if (!response.ok) {
    throw new Error(`Failed to get summary: ${response.statusText}`);
  }

  return response.json();
}
