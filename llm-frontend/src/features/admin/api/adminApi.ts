/**
 * Admin API client for book ingestion
 */

import {
  Book,
  BookDetail,
  CreateBookRequest,
  PageUploadResponse,
  PageDetails,
  GuidelinesListResponse,
  GuidelineSubtopic,
  GenerateGuidelinesRequest,
  GenerateGuidelinesStartResponse,
  JobStatus,
  BulkUploadResponse,
  GuidelineReview,
  GuidelineFilters,
  StudyPlan,
  EvalRunSummary,
  EvalRunDetail,
  EvalStatus,
  StartEvalRequest,
  SessionListResponse,
  EvaluateSessionRequest,
  LLMConfig,
  LLMConfigOptions,
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

// ===== Book Management =====

export async function createBook(data: CreateBookRequest): Promise<Book> {
  return apiFetch<Book>('/admin/books', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function listBooks(filters?: {
  country?: string;
  board?: string;
  grade?: number;
  subject?: string;
  status?: string;
}): Promise<{ books: Book[]; total: number }> {
  const params = new URLSearchParams();
  if (filters) {
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.append(key, String(value));
      }
    });
  }

  const query = params.toString();
  return apiFetch<{ books: Book[]; total: number }>(
    `/admin/books${query ? `?${query}` : ''}`
  );
}

export async function getBook(bookId: string): Promise<BookDetail> {
  return apiFetch<BookDetail>(`/admin/books/${bookId}`);
}



export async function deleteBook(bookId: string): Promise<void> {
  return apiFetch<void>(`/admin/books/${bookId}`, {
    method: 'DELETE',
  });
}

// ===== Page Management =====

export async function uploadPage(
  bookId: string,
  imageFile: File
): Promise<PageUploadResponse> {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await fetch(`${API_BASE_URL}/admin/books/${bookId}/pages`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

export async function approvePage(
  bookId: string,
  pageNum: number
): Promise<{ page_num: number; status: string }> {
  return apiFetch(`/admin/books/${bookId}/pages/${pageNum}/approve`, {
    method: 'PUT',
  });
}

export async function deletePage(bookId: string, pageNum: number): Promise<void> {
  return apiFetch<void>(`/admin/books/${bookId}/pages/${pageNum}`, {
    method: 'DELETE',
  });
}

export async function getPage(
  bookId: string,
  pageNum: number
): Promise<PageDetails> {
  return apiFetch<PageDetails>(`/admin/books/${bookId}/pages/${pageNum}`);
}

// ===== Guideline Management (Phase 6) =====

export async function generateGuidelines(
  bookId: string,
  request: GenerateGuidelinesRequest
): Promise<GenerateGuidelinesStartResponse> {
  return apiFetch<GenerateGuidelinesStartResponse>(
    `/admin/books/${bookId}/generate-guidelines`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }
  );
}

export async function getGuidelines(
  bookId: string
): Promise<GuidelinesListResponse> {
  return apiFetch<GuidelinesListResponse>(`/admin/books/${bookId}/guidelines`);
}

export async function getGuideline(
  bookId: string,
  topicKey: string,
  subtopicKey: string
): Promise<GuidelineSubtopic> {
  return apiFetch<GuidelineSubtopic>(
    `/admin/books/${bookId}/guidelines/${topicKey}/${subtopicKey}`
  );
}

export async function approveGuidelines(
  bookId: string
): Promise<{ book_id: string; status: string; synced_count: number }> {
  return apiFetch(`/admin/books/${bookId}/guidelines/approve`, {
    method: 'PUT',
  });
}

export async function rejectGuidelines(bookId: string): Promise<void> {
  return apiFetch<void>(`/admin/books/${bookId}/guidelines`, {
    method: 'DELETE',
  });
}

export async function finalizeGuidelines(
  bookId: string,
  autoSyncToDb: boolean = false
): Promise<{
  job_id: string;
  status: string;
  message: string;
}> {
  return apiFetch(`/admin/books/${bookId}/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_sync_to_db: autoSyncToDb }),
  });
}

// ===== Job Status =====

export async function getLatestJob(
  bookId: string,
  jobType?: string
): Promise<JobStatus | null> {
  const params = jobType ? `?job_type=${jobType}` : '';
  return apiFetch<JobStatus | null>(`/admin/books/${bookId}/jobs/latest${params}`);
}

export async function getJobStatus(
  bookId: string,
  jobId: string
): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/admin/books/${bookId}/jobs/${jobId}`);
}

// ===== Bulk Upload =====

export async function bulkUploadPages(
  bookId: string,
  imageFiles: File[]
): Promise<BulkUploadResponse> {
  const formData = new FormData();
  imageFiles.forEach(file => {
    formData.append('images', file);
  });

  const response = await fetch(`${API_BASE_URL}/admin/books/${bookId}/pages/bulk`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ===== OCR Retry =====

export async function retryPageOcr(
  bookId: string,
  pageNum: number
): Promise<{ page_num: number; ocr_status: string }> {
  return apiFetch(`/admin/books/${bookId}/pages/${pageNum}/retry-ocr`, {
    method: 'POST',
  });
}

// ===== Guidelines Review =====

export async function getGuidelineFilters(): Promise<GuidelineFilters> {
  return apiFetch<GuidelineFilters>('/admin/guidelines/review/filters');
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
    `/admin/guidelines/review${query ? `?${query}` : ''}`
  );
}

export async function approveGuideline(guidelineId: string): Promise<{ id: string; review_status: string }> {
  return apiFetch(`/admin/guidelines/${guidelineId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved: true }),
  });
}

export async function rejectGuideline(guidelineId: string): Promise<{ id: string; review_status: string }> {
  return apiFetch(`/admin/guidelines/${guidelineId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved: false }),
  });
}

export async function deleteGuideline(guidelineId: string): Promise<{ message: string; id: string }> {
  return apiFetch(`/admin/guidelines/${guidelineId}`, {
    method: 'DELETE',
  });
}

// ===== Study Plans =====

export async function generateStudyPlan(
  guidelineId: string,
  forceRegenerate: boolean = false
): Promise<StudyPlan> {
  const query = forceRegenerate ? '?force_regenerate=true' : '';
  return apiFetch<StudyPlan>(`/admin/guidelines/${guidelineId}/generate-study-plan${query}`, {
    method: 'POST',
  });
}

export async function getStudyPlan(guidelineId: string): Promise<StudyPlan> {
  return apiFetch<StudyPlan>(`/admin/guidelines/${guidelineId}/study-plan`);
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
  modelId: string
): Promise<LLMConfig> {
  return apiFetch<LLMConfig>(`/api/admin/llm-config/${componentKey}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, model_id: modelId }),
  });
}

export async function getLLMConfigOptions(): Promise<LLMConfigOptions> {
  return apiFetch<LLMConfigOptions>('/api/admin/llm-config/options');
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
