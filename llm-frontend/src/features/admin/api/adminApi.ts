/**
 * Admin API client
 */

import {
  EvalRunSummary,
  EvalRunDetail,
  EvalStatus,
  StartEvalRequest,
  SessionListResponse,
  EvaluateSessionRequest,
  LLMConfig,
  LLMConfigOptions,
  FeatureFlag,
} from '../types';

// Use environment variable for production, fallback to localhost for development
const API_BASE_URL = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Helper function for API calls
async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

// ===== Guidelines (used by Evaluation) =====

export interface GuidelineReview {
  id: string;
  country: string;
  board: string;
  grade: number;
  subject: string;
  chapter: string;
  topic: string;
  guideline: string;
  review_status: 'TO_BE_REVIEWED' | 'APPROVED';
  updated_at: string;
}

export async function getAllGuidelinesForReview(filters?: {
  country?: string;
  board?: string;
  grade?: number;
  subject?: string;
  status?: 'TO_BE_REVIEWED' | 'APPROVED';
}): Promise<GuidelineReview[]> {
  const params = new URLSearchParams();
  if (filters) {
    if (filters.country) params.append('country', filters.country);
    if (filters.board) params.append('board', filters.board);
    if (filters.grade) params.append('grade', filters.grade.toString());
    if (filters.subject) params.append('subject', filters.subject);
    if (filters.status) params.append('status', filters.status);
  }
  const query = params.toString();
  return apiFetch<GuidelineReview[]>(
    `/api/evaluation/guidelines${query ? `?${query}` : ''}`
  );
}

// ===== Evaluation Personas =====

export interface EvalPersona {
  persona_id: string;
  name: string;
  file: string;
  grade: number | null;
  age: number | null;
  description: string;
  correct_answer_probability: number;
}

export async function listEvalPersonas(): Promise<EvalPersona[]> {
  return apiFetch<EvalPersona[]>('/api/evaluation/personas');
}

// ===== Evaluation Pipeline =====

export async function listEvalRuns(): Promise<EvalRunSummary[]> {
  return apiFetch<EvalRunSummary[]>('/api/evaluation/runs');
}

export async function getEvalRun(runId: string): Promise<EvalRunDetail> {
  return apiFetch<EvalRunDetail>(`/api/evaluation/runs/${runId}`);
}

export async function startEvaluation(request: StartEvalRequest): Promise<{ status: string; topic_id: string; max_turns: number }> {
  return apiFetch('/api/evaluation/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export async function getEvalStatus(): Promise<EvalStatus> {
  return apiFetch<EvalStatus>('/api/evaluation/status');
}

// ===== Sessions =====

export async function listSessions(): Promise<SessionListResponse> {
  return apiFetch<SessionListResponse>('/sessions');
}

export async function evaluateSession(request: EvaluateSessionRequest): Promise<{ status: string; session_id: string }> {
  return apiFetch('/api/evaluation/evaluate-session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

// ===== Documentation =====

export interface DocEntry {
  filename: string;
  title: string;
}

export interface DocsIndex {
  functional?: DocEntry[];
  technical?: DocEntry[];
  root?: DocEntry[];
}

export interface DocContent {
  filename: string;
  category: string;
  content: string;
}

export async function listDocs(): Promise<DocsIndex> {
  return apiFetch<DocsIndex>('/api/docs');
}

export async function getDocContent(category: string, filename: string): Promise<DocContent> {
  return apiFetch<DocContent>(`/api/docs/${category}/${filename}`);
}

// ===== LLM Config =====

export async function getLLMConfigs(): Promise<LLMConfig[]> {
  return apiFetch<LLMConfig[]>('/api/admin/llm-config');
}

export async function updateLLMConfig(
  componentKey: string,
  provider: string,
  modelId: string,
  reasoningEffort: string
): Promise<LLMConfig> {
  return apiFetch<LLMConfig>(`/api/admin/llm-config/${componentKey}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider,
      model_id: modelId,
      reasoning_effort: reasoningEffort,
    }),
  });
}

export async function getLLMConfigOptions(): Promise<LLMConfigOptions> {
  return apiFetch<LLMConfigOptions>('/api/admin/llm-config/options');
}

// ===== TTS Config =====

export interface TTSConfigResponse {
  provider: string;
  available_providers: string[];
}

export async function getTTSConfig(): Promise<TTSConfigResponse> {
  return apiFetch<TTSConfigResponse>('/api/admin/tts-config');
}

export async function updateTTSConfig(provider: string): Promise<unknown> {
  return apiFetch<unknown>('/api/admin/tts-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider }),
  });
}

// ===== Feature Flags =====

export async function getFeatureFlags(): Promise<FeatureFlag[]> {
  return apiFetch<FeatureFlag[]>('/api/admin/feature-flags');
}

export async function updateFeatureFlag(
  flagName: string,
  enabled: boolean
): Promise<FeatureFlag> {
  return apiFetch<FeatureFlag>(`/api/admin/feature-flags/${flagName}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}

// ===== Test Scenarios =====

export interface TestFunctionality {
  slug: string;
  name: string;
  filename: string;
  scenario_count: number;
  last_tested: string | null;
  status: 'passed' | 'failed' | 'not_run';
  passed: number;
  failed: number;
}

export interface TestScenarioResult {
  id: string;
  name: string;
  status: 'passed' | 'failed' | 'not_run';
  steps: string[];
  expected_result: string;
  screenshots: string[];
}

export interface TestFunctionalityDetail {
  slug: string;
  name: string;
  last_tested: string | null;
  status: string;
  scenarios: TestScenarioResult[];
}

export interface ScreenshotInfo {
  label: string;
  url: string;
  filename: string;
}

export async function listTestScenarios(): Promise<{ functionalities: TestFunctionality[] }> {
  return apiFetch<{ functionalities: TestFunctionality[] }>('/api/test-scenarios');
}

export async function getTestScenarioDetail(slug: string): Promise<TestFunctionalityDetail> {
  return apiFetch<TestFunctionalityDetail>(`/api/test-scenarios/${slug}`);
}

export async function getScenarioScreenshots(
  slug: string,
  scenarioId: string
): Promise<{ scenario_id: string; screenshots: ScreenshotInfo[] }> {
  return apiFetch<{ scenario_id: string; screenshots: ScreenshotInfo[] }>(
    `/api/test-scenarios/${slug}/screenshots/${scenarioId}`
  );
}
