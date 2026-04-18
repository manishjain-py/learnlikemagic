/**
 * Admin API client for Book Ingestion V2.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  return response.json();
}

// ===== Book Management =====

export async function createBookV2(data: CreateBookV2Request): Promise<BookV2Response> {
  return apiFetch<BookV2Response>('/admin/v2/books', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function listBooksV2(): Promise<BookV2ListResponse> {
  return apiFetch<BookV2ListResponse>('/admin/v2/books');
}

export async function getBookV2(bookId: string): Promise<BookV2DetailResponse> {
  return apiFetch<BookV2DetailResponse>(`/admin/v2/books/${bookId}`);
}

export async function deleteBookV2(bookId: string): Promise<void> {
  return apiFetch<void>(`/admin/v2/books/${bookId}`, { method: 'DELETE' });
}

// ===== TOC Management =====

export async function saveTOC(bookId: string, chapters: TOCEntry[]): Promise<TOCResponse> {
  return apiFetch<TOCResponse>(`/admin/v2/books/${bookId}/toc`, {
    method: 'POST',
    body: JSON.stringify({ chapters }),
  });
}

export async function getTOC(bookId: string): Promise<TOCResponse> {
  return apiFetch<TOCResponse>(`/admin/v2/books/${bookId}/toc`);
}

export async function updateChapter(
  bookId: string, chapterId: string, data: TOCEntry
): Promise<ChapterResponseV2> {
  return apiFetch<ChapterResponseV2>(`/admin/v2/books/${bookId}/toc/${chapterId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteChapter(bookId: string, chapterId: string): Promise<void> {
  return apiFetch<void>(`/admin/v2/books/${bookId}/toc/${chapterId}`, { method: 'DELETE' });
}

export async function extractTOCFromImages(
  bookId: string, images: File[]
): Promise<TOCExtractionResponse> {
  const formData = new FormData();
  images.forEach((img) => formData.append('images', img));

  const url = `${API_BASE_URL}/admin/v2/books/${bookId}/toc/extract`;
  const response = await fetch(url, { method: 'POST', body: formData });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `TOC extraction failed: ${response.status}`);
  }
  return response.json();
}

// ===== Pages (per chapter) =====

export async function uploadPageV2(
  bookId: string, chapterId: string, pageNum: number, file: File
): Promise<PageResponseV2> {
  const formData = new FormData();
  formData.append('image', file);
  formData.append('page_number', pageNum.toString());

  const url = `${API_BASE_URL}/admin/v2/books/${bookId}/chapters/${chapterId}/pages`;
  const response = await fetch(url, { method: 'POST', body: formData });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Upload failed: ${response.status}`);
  }
  return response.json();
}

export async function getChapterPages(
  bookId: string, chapterId: string
): Promise<ChapterPagesResponseV2> {
  return apiFetch<ChapterPagesResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/pages`
  );
}

export async function deletePageV2(
  bookId: string, chapterId: string, pageNum: number
): Promise<void> {
  return apiFetch<void>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/pages/${pageNum}`,
    { method: 'DELETE' }
  );
}

export async function retryPageOcrV2(
  bookId: string, chapterId: string, pageNum: number
): Promise<PageResponseV2> {
  return apiFetch<PageResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/pages/${pageNum}/retry-ocr`,
    { method: 'POST' }
  );
}

export async function getPageDetailV2(
  bookId: string, chapterId: string, pageNum: number
): Promise<PageDetailResponseV2> {
  return apiFetch<PageDetailResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/pages/${pageNum}/detail`
  );
}

// ===== Processing =====

export async function startProcessing(
  bookId: string, chapterId: string, resume = false
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/process`,
    { method: 'POST', body: JSON.stringify({ resume }) }
  );
}

export async function reprocessChapter(
  bookId: string, chapterId: string
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/reprocess`,
    { method: 'POST', body: JSON.stringify({}) }
  );
}

export async function refinalizeChapter(
  bookId: string, chapterId: string
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/refinalize`,
    { method: 'POST', body: JSON.stringify({}) }
  );
}

export async function bulkOcrRetry(
  bookId: string, chapterId: string
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/ocr-retry`,
    { method: 'POST' }
  );
}

export async function bulkOcrRerun(
  bookId: string, chapterId: string
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/ocr-rerun`,
    { method: 'POST' }
  );
}

export async function getLatestJobV2(
  bookId: string, chapterId: string, jobType?: string
): Promise<ProcessingJobResponseV2> {
  const params = jobType ? `?job_type=${jobType}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/jobs/latest${params}`
  );
}

export async function getJobStatusV2(
  bookId: string, chapterId: string, jobId: string
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/jobs/${jobId}`
  );
}

// ===== Topics =====

export async function getChapterTopics(
  bookId: string, chapterId: string
): Promise<ChapterTopicsResponseV2> {
  return apiFetch<ChapterTopicsResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/topics`
  );
}

export async function getTopicDetail(
  bookId: string, chapterId: string, topicKey: string
): Promise<ChapterTopicResponseV2> {
  return apiFetch<ChapterTopicResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/topics/${topicKey}`
  );
}

export async function deleteTopic(
  bookId: string, chapterId: string, topicId: string
): Promise<{ deleted: string }> {
  return apiFetch(`/admin/v2/books/${bookId}/chapters/${chapterId}/topics/${topicId}`, { method: 'DELETE' });
}

// ===== Sync =====

export async function syncBook(bookId: string): Promise<SyncResponseV2> {
  return apiFetch<SyncResponseV2>(`/admin/v2/books/${bookId}/sync`, { method: 'POST' });
}

export async function syncChapter(
  bookId: string, chapterId: string
): Promise<SyncResponseV2> {
  return apiFetch<SyncResponseV2>(
    `/admin/v2/books/${bookId}/chapters/${chapterId}/sync`,
    { method: 'POST' }
  );
}

// ===== Explanation Generation =====

export async function generateExplanations(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; force?: boolean; mode?: string; reviewRounds?: number },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.force) params.set('force', 'true');
  if (opts?.mode) params.set('mode', opts.mode);
  if (opts?.reviewRounds !== undefined) params.set('review_rounds', opts.reviewRounds.toString());
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-explanations${qs}`,
    { method: 'POST' }
  );
}

export interface StageSnapshotV2 {
  guideline_id: string;
  topic_title: string;
  variant_key: string;
  stage: string;
  cards: ExplanationCardV2[];
  timestamp?: string;
}

export async function getJobStageSnapshots(
  bookId: string,
  jobId: string,
  guidelineId?: string,
): Promise<{ job_id: string; snapshots: StageSnapshotV2[] }> {
  const params = guidelineId ? `?guideline_id=${guidelineId}` : '';
  return apiFetch(`/admin/v2/books/${bookId}/explanation-jobs/${jobId}/stages${params}`);
}

export async function getExplanationJobStatus(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/explanation-jobs/latest${qs}`
  );
}

export async function getExplanationStatus(
  bookId: string, chapterId: string
): Promise<ExplanationStatusResponseV2> {
  return apiFetch<ExplanationStatusResponseV2>(
    `/admin/v2/books/${bookId}/explanation-status?chapter_id=${chapterId}`
  );
}

export async function getTopicExplanations(
  bookId: string, guidelineId: string
): Promise<TopicExplanationsDetailResponseV2> {
  return apiFetch<TopicExplanationsDetailResponseV2>(
    `/admin/v2/books/${bookId}/explanations?guideline_id=${guidelineId}`
  );
}

export async function deleteExplanations(
  bookId: string,
  opts: { guidelineId?: string; chapterId?: string },
): Promise<DeleteExplanationsResponseV2> {
  const params = new URLSearchParams();
  if (opts.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts.chapterId) params.set('chapter_id', opts.chapterId);
  return apiFetch<DeleteExplanationsResponseV2>(
    `/admin/v2/books/${bookId}/explanations?${params.toString()}`,
    { method: 'DELETE' }
  );
}

// ===== Refresher Generation =====

export async function generateRefresher(
  bookId: string,
  chapterId: string,
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/refresher/generate?chapter_id=${chapterId}`,
    { method: 'POST' }
  );
}

export async function getRefresherJobStatus(
  bookId: string,
  chapterId: string,
): Promise<ProcessingJobResponseV2> {
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/refresher-jobs/latest?chapter_id=${chapterId}`
  );
}

// ===== Results =====

export async function getBookResults(bookId: string): Promise<BookResultsResponseV2> {
  return apiFetch<BookResultsResponseV2>(`/admin/v2/books/${bookId}/results`);
}

// ===== TypeScript Types =====

export interface CreateBookV2Request {
  title: string;
  author?: string;
  edition?: string;
  edition_year?: number;
  country: string;
  board: string;
  grade: number;
  subject: string;
}

export interface BookV2Response {
  id: string;
  title: string;
  author?: string;
  edition?: string;
  edition_year?: number;
  country: string;
  board: string;
  grade: number;
  subject: string;
  pipeline_version: number;
  chapter_count: number;
  created_at?: string;
  updated_at?: string;
  created_by?: string;
}

export interface BookV2ListResponse {
  books: BookV2Response[];
  total: number;
}

export interface TOCEntry {
  chapter_number: number;
  chapter_title: string;
  start_page: number;
  end_page: number;
  notes?: string | null;
}

export interface TOCExtractionResponse {
  chapters: TOCEntry[];
  raw_ocr_text: string;
}

export interface ChapterResponseV2 {
  id: string;
  chapter_number: number;
  chapter_title: string;
  start_page: number;
  end_page: number;
  notes?: string | null;
  display_name?: string;
  summary?: string;
  status: string;
  total_pages: number;
  uploaded_page_count: number;
  error_message?: string;
  error_type?: string;
  created_at?: string;
  updated_at?: string;
}

export interface TOCResponse {
  book_id: string;
  chapters: ChapterResponseV2[];
}

export interface BookV2DetailResponse {
  id: string;
  title: string;
  author?: string;
  edition?: string;
  edition_year?: number;
  country: string;
  board: string;
  grade: number;
  subject: string;
  pipeline_version: number;
  chapters: ChapterResponseV2[];
  created_at?: string;
  updated_at?: string;
}

export interface PageResponseV2 {
  id: string;
  page_number: number;
  chapter_id: string;
  image_s3_key?: string;
  text_s3_key?: string;
  ocr_status: string;
  ocr_error?: string;
  uploaded_at?: string;
  ocr_completed_at?: string;
}

export interface PageDetailResponseV2 {
  id: string;
  page_number: number;
  chapter_id: string;
  image_url?: string;
  ocr_text?: string;
  ocr_status: string;
  ocr_error?: string;
  uploaded_at?: string;
  ocr_completed_at?: string;
}

export interface ChapterPagesResponseV2 {
  chapter_id: string;
  total_pages: number;
  uploaded_count: number;
  pages: PageResponseV2[];
}

export interface ProcessingJobResponseV2 {
  job_id: string;
  chapter_id: string;
  job_type: string;
  status: 'pending' | 'running' | 'completed' | 'completed_with_errors' | 'failed';
  total_items?: number;
  completed_items: number;
  failed_items: number;
  current_item?: string;
  last_completed_item?: string;
  progress_detail?: Record<string, unknown>;
  model_provider?: string;
  model_id?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
}

export interface ChapterTopicResponseV2 {
  id: string;
  topic_key: string;
  topic_title: string;
  guidelines: string;
  summary?: string;
  source_page_start?: number;
  source_page_end?: number;
  sequence_order?: number;
  status: string;
  version: number;
}

export interface ChapterTopicsResponseV2 {
  chapter_id: string;
  topics: ChapterTopicResponseV2[];
  total: number;
}

export interface SyncResponseV2 {
  synced_chapters: number;
  synced_topics: number;
  errors: string[];
}

export interface ChapterResultSummaryV2 {
  chapter_id: string;
  chapter_number: number;
  chapter_title: string;
  display_name?: string;
  status: string;
  topic_count: number;
}

export interface BookResultsResponseV2 {
  book_id: string;
  title: string;
  chapters: ChapterResultSummaryV2[];
  total_topics: number;
}

// ===== Explanation Status & Detail Types =====

export interface TopicExplanationStatusV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  variant_count: number;
}

export interface ExplanationStatusResponseV2 {
  chapter_id: string;
  chapter_key: string;
  topics: TopicExplanationStatusV2[];
}

export interface ExplanationCardV2 {
  card_idx: number;
  card_type: string;
  title: string;
  content: string;
  visual?: string | null;
  audio_text?: string | null;
}

export interface ExplanationVariantV2 {
  id: string;
  variant_key: string;
  variant_label: string;
  cards_json: ExplanationCardV2[];
  summary_json?: Record<string, unknown> | null;
  generator_model?: string;
  created_at?: string;
}

export interface TopicExplanationsDetailResponseV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  variants: ExplanationVariantV2[];
}

export interface DeleteExplanationsResponseV2 {
  deleted_count: number;
}

// ===== Guideline Admin Types & API =====

export interface GuidelineStatusItemV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  review_status: string;
  guideline_preview?: string;
  has_explanations: boolean;
  source_page_start?: number;
  source_page_end?: number;
}

export interface ChapterGuidelineStatusResponseV2 {
  chapter_id: string;
  chapter_key: string;
  guidelines: GuidelineStatusItemV2[];
}

export interface GuidelineDetailResponseV2 {
  id: string;
  topic_title: string;
  topic_key?: string;
  chapter_key?: string;
  guideline: string;
  review_status: string;
  source_page_start?: number;
  source_page_end?: number;
  metadata_json?: Record<string, unknown> | null;
  topic_summary?: string;
  updated_at?: string;
}

export async function getGuidelineStatus(
  bookId: string, chapterId: string
): Promise<ChapterGuidelineStatusResponseV2> {
  return apiFetch<ChapterGuidelineStatusResponseV2>(
    `/admin/v2/books/${bookId}/guideline-status?chapter_id=${chapterId}`
  );
}

export async function getGuidelineDetail(
  bookId: string, guidelineId: string
): Promise<GuidelineDetailResponseV2> {
  return apiFetch<GuidelineDetailResponseV2>(
    `/admin/v2/books/${bookId}/guidelines/${guidelineId}`
  );
}

export async function updateGuideline(
  bookId: string, guidelineId: string, data: { guideline?: string; review_status?: string }
): Promise<GuidelineDetailResponseV2> {
  return apiFetch<GuidelineDetailResponseV2>(
    `/admin/v2/books/${bookId}/guidelines/${guidelineId}`,
    { method: 'PUT', body: JSON.stringify(data) }
  );
}

export async function deleteGuideline(
  bookId: string, guidelineId: string
): Promise<{ deleted_guideline: string; deleted_explanations: number }> {
  return apiFetch(`/admin/v2/books/${bookId}/guidelines/${guidelineId}`, { method: 'DELETE' });
}

// ===== Visual Enrichment Admin Types & API =====

export interface TopicVisualStatusV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  total_cards: number;
  cards_with_visuals: number;
  has_explanations: boolean;
}

export interface ChapterVisualStatusResponseV2 {
  chapter_id: string;
  chapter_key: string;
  topics: TopicVisualStatusV2[];
}

export async function getVisualStatus(
  bookId: string, chapterId: string
): Promise<ChapterVisualStatusResponseV2> {
  return apiFetch<ChapterVisualStatusResponseV2>(
    `/admin/v2/books/${bookId}/visual-status?chapter_id=${chapterId}`
  );
}

export async function generateVisuals(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; force?: boolean },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.force) params.set('force', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-visuals${qs}`,
    { method: 'POST' }
  );
}

export async function deleteVisuals(
  bookId: string, guidelineId: string
): Promise<{ guideline_id: string; visuals_stripped: number }> {
  return apiFetch(`/admin/v2/books/${bookId}/visuals?guideline_id=${guidelineId}`, { method: 'DELETE' });
}

export async function getVisualJobStatus(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/visual-jobs/latest${qs}`
  );
}

// ===== Check-In Enrichment Admin Types & API =====

export interface TopicCheckInStatusV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  total_cards: number;
  cards_with_check_ins: number;
  has_explanations: boolean;
}

export interface ChapterCheckInStatusResponseV2 {
  chapter_id: string;
  chapter_key: string;
  topics: TopicCheckInStatusV2[];
}

export async function getCheckInStatus(
  bookId: string, chapterId: string
): Promise<ChapterCheckInStatusResponseV2> {
  return apiFetch<ChapterCheckInStatusResponseV2>(
    `/admin/v2/books/${bookId}/check-in-status?chapter_id=${chapterId}`
  );
}

export async function generateCheckIns(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; force?: boolean; reviewRounds?: number },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.force) params.set('force', 'true');
  if (opts?.reviewRounds !== undefined) params.set('review_rounds', opts.reviewRounds.toString());
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-check-ins${qs}`,
    { method: 'POST' }
  );
}

export async function getCheckInJobStatus(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/check-in-jobs/latest${qs}`
  );
}

// ===== Practice Bank Generation =====

export interface TopicPracticeBankStatusV2 {
  guideline_id: string;
  topic_title: string;
  topic_key?: string;
  question_count: number;
  has_explanations: boolean;
}

export interface ChapterPracticeBankStatusResponseV2 {
  chapter_id: string;
  chapter_key: string;
  topics: TopicPracticeBankStatusV2[];
}

export interface PracticeBankQuestionItemV2 {
  id: string;
  format: string;
  difficulty: string;
  concept_tag: string;
  question_json: Record<string, unknown>;
  generator_model?: string | null;
  created_at: string;
}

export interface PracticeBankDetailResponseV2 {
  guideline_id: string;
  topic_title: string;
  question_count: number;
  questions: PracticeBankQuestionItemV2[];
}

export async function getPracticeBankStatus(
  bookId: string, chapterId: string
): Promise<ChapterPracticeBankStatusResponseV2> {
  return apiFetch<ChapterPracticeBankStatusResponseV2>(
    `/admin/v2/books/${bookId}/practice-bank-status?chapter_id=${chapterId}`
  );
}

export async function generatePracticeBanks(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; force?: boolean; reviewRounds?: number },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.force) params.set('force', 'true');
  if (opts?.reviewRounds !== undefined) params.set('review_rounds', opts.reviewRounds.toString());
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-practice-banks${qs}`,
    { method: 'POST' }
  );
}

export async function getPracticeBankJobStatus(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/practice-bank-jobs/latest${qs}`
  );
}

export async function getPracticeBank(
  bookId: string, guidelineId: string
): Promise<PracticeBankDetailResponseV2> {
  return apiFetch<PracticeBankDetailResponseV2>(
    `/admin/v2/books/${bookId}/practice-banks/${guidelineId}`
  );
}

// ===== Audio Generation =====

export async function generateAudio(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-audio${qs}`,
    { method: 'POST' }
  );
}
