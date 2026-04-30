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
  chapter: string;
  syllabus: string;
  learning_objectives: string[];
  guideline_id: string;
}

export type TeachMeMode = 'explain' | 'baatcheet';

export interface CreateSessionRequest {
  student: Student;
  goal: Goal;
  mode?: 'teach_me' | 'clarify_doubts';
  teach_me_mode?: TeachMeMode;
}

export interface VisualExplanation {
  pixi_code?: string;       // Generated Pixi.js v8 JavaScript code
  output_type?: 'image' | 'animation';
  title?: string;
  narration?: string;
  layout_warning?: boolean; // True when stage-7 visual review gate still flagged the card after the targeted refine round. Admin observability only — no student-facing UI.
  // Legacy fields from old SVG-based visuals (backward compat)
  scene_type?: string;
}

export interface MatchPair {
  left: string;
  right: string;
}

export interface BucketItem {
  text: string;
  correct_bucket: number;  // 0 or 1 — index into bucket_names
}

export interface CheckInActivity {
  activity_type: 'pick_one' | 'true_false' | 'fill_blank' | 'match_pairs' | 'sort_buckets' | 'sequence'
    | 'spot_the_error' | 'odd_one_out' | 'predict_then_reveal' | 'swipe_classify' | 'tap_to_eliminate';
  instruction: string;
  hint: string;
  success_message: string;
  audio_text: string;

  // Pre-computed TTS audio URLs (populated by offline synth; optional).
  // Frontend falls back to live synthesizeSpeech when any URL is absent.
  audio_text_url?: string;
  hint_audio_url?: string;
  success_audio_url?: string;
  reveal_audio_url?: string;  // predict_then_reveal only

  // pick_one / fill_blank / predict_then_reveal / tap_to_eliminate
  options?: string[];
  correct_index?: number;

  // true_false
  statement?: string;
  correct_answer?: boolean;

  // match_pairs
  pairs?: MatchPair[];

  // sort_buckets / swipe_classify
  bucket_names?: string[];
  bucket_items?: BucketItem[];

  // sequence
  sequence_items?: string[];  // in correct order; frontend shuffles for display

  // spot_the_error
  error_steps?: string[];
  error_index?: number;

  // odd_one_out
  odd_items?: string[];
  odd_index?: number;

  // predict_then_reveal
  reveal_text?: string;
}

export interface ExplanationLine {
  display: string;  // Markdown line shown on screen
  audio: string;    // TTS-friendly spoken version
}

export interface ExplanationCard {
  card_id?: string;
  card_idx: number;
  card_type: 'concept' | 'example' | 'visual' | 'analogy' | 'summary' | 'simplification' | 'check_in' | 'welcome';
  title: string;
  lines: ExplanationLine[];  // Per-line display+audio pairs
  content: string;  // Derived from joining lines[].display
  visual?: string | null;
  audio_text?: string | null;  // Derived from joining lines[].audio
  visual_explanation?: VisualExplanation | null;  // Pre-computed PixiJS visual
  check_in?: CheckInActivity | null;  // Interactive check-in activity (6 types)
  source_card_idx?: number;
  simplifications?: {
    content: string;
    title?: string;
    lines?: ExplanationLine[];
    audio_text?: string;
    visual_explanation?: VisualExplanation | null;
  }[];
}

export interface CardPhaseDTO {
  current_variant_key: string;
  current_card_idx: number;
  total_cards: number;
  available_variants: number;
}

// ───── Baatcheet (dialogue phase) ─────

export type DialogueSpeaker = 'tutor' | 'peer';
export type DialogueCardType =
  | 'welcome'
  | 'tutor_turn'
  | 'peer_turn'
  | 'visual'
  | 'check_in'
  | 'summary';

export interface DialogueLine {
  display: string;
  audio: string;
  audio_url?: string | null;
}

export interface DialogueCard {
  card_id: string;
  card_idx: number;
  card_type: DialogueCardType;
  speaker: DialogueSpeaker | null;
  speaker_name: string | null;
  title: string | null;
  lines: DialogueLine[];
  audio_url: string | null;
  includes_student_name: boolean;
  visual: string | null;
  visual_intent: string | null;
  visual_explanation: VisualExplanation | null;
  check_in: CheckInActivity | null;
}

export interface DialoguePhaseDTO {
  current_card_idx: number;
  total_cards: number;
}

export interface Personalization {
  student_name: string | null;
  fallback_student_name: string;
  topic_name: string;
}

export interface CardProgressRequest {
  phase: 'card_phase' | 'dialogue_phase';
  card_idx: number;
  mark_complete?: boolean;
  check_in_events?: Array<Record<string, unknown>>;
}

export interface TeachMeOptionState {
  available: boolean;
  card_count: number | null;
  is_stale: boolean;
  in_progress_session_id: string | null;
  completed_session_id: string | null;
  current_card_idx: number | null;
  total_cards: number | null;
  is_complete: boolean;
}

export interface TeachMeOptionsResponse {
  guideline_id: string;
  baatcheet: TeachMeOptionState;
  explain: TeachMeOptionState;
}

export interface BlankItem {
  blank_id: number;
  correct_answer: string;
}

export interface OptionItem {
  key: string;
  text: string;
  correct: boolean;
}

export interface QuestionFormat {
  type: 'fill_in_the_blank' | 'single_select' | 'multi_select' | 'acknowledge';
  sentence_template?: string;
  blanks?: BlankItem[];
  options?: OptionItem[];
}

export interface Turn {
  message: string;
  audio_text?: string | null;
  hints: string[];
  step_idx: number;
  mastery_score?: number;
  is_complete?: boolean;
  visual_explanation?: VisualExplanation | null;
  question_format?: QuestionFormat | null;
  concepts_discussed?: string[];
  // Card phase fields (pre-computed explanations)
  explanation_cards?: ExplanationCard[];
  session_phase?: 'card_phase' | 'dialogue_phase' | 'interactive';
  card_phase_state?: CardPhaseDTO;
  // Baatcheet (dialogue phase) fields
  dialogue_cards?: DialogueCard[];
  dialogue_phase_state?: DialoguePhaseDTO;
  teach_me_mode?: TeachMeMode;
  personalization?: Personalization;
}

export interface CreateSessionResponse {
  session_id: string;
  first_turn: Turn;
  mode?: string;
  teach_me_mode?: TeachMeMode;
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
  concepts_taught?: string[];
}

export interface ChapterInfo {
  chapter: string;
  chapter_summary: string | null;
  chapter_sequence: number | null;
  topic_count: number;
  guideline_ids: string[];
  refresher_guideline_id: string | null;
}

export interface TopicInfo {
  topic: string;
  guideline_id: string;
  topic_key: string | null;
  topic_summary: string | null;
  topic_sequence: number | null;
}

export interface CurriculumResponse {
  subjects?: string[];
  chapters?: ChapterInfo[];
  topics?: TopicInfo[];
}

// ──────────────────────────────────────────────
// API functions (updated to use apiFetch)
// ──────────────────────────────────────────────

export async function getCurriculum(params: {
  country: string;
  board: string;
  grade: number;
  subject?: string;
  chapter?: string;
}): Promise<CurriculumResponse> {
  const queryParams = new URLSearchParams({
    country: params.country,
    board: params.board,
    grade: params.grade.toString(),
    ...(params.subject && { subject: params.subject }),
    ...(params.chapter && { chapter: params.chapter }),
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

export interface ReportCardTopic {
  topic: string;
  topic_key: string;
  guideline_id: string | null;
  coverage: number;
  latest_practice_score?: number | null;
  latest_practice_total?: number | null;
  practice_attempt_count?: number | null;
  last_studied: string | null;
}

export interface ReportCardChapter {
  chapter: string;
  chapter_key: string;
  topics: ReportCardTopic[];
}

export interface ReportCardSubject {
  subject: string;
  chapters: ReportCardChapter[];
}

export interface ReportCardResponse {
  total_sessions: number;
  total_chapters_studied: number;
  subjects: ReportCardSubject[];
}

export interface TopicProgress {
  coverage: number;
  session_count: number;
  status: 'studied' | 'not_started';
}

export interface ResumableSession {
  session_id: string;
  mode: 'teach_me';
  teach_me_mode?: TeachMeMode | null;
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

export async function getReportCard(): Promise<ReportCardResponse> {
  const response = await apiFetch('/sessions/report-card');
  if (!response.ok) throw new Error(`Failed to fetch report card: ${response.statusText}`);
  return response.json();
}

export async function getTopicProgress(): Promise<Record<string, TopicProgress>> {
  const response = await apiFetch('/sessions/topic-progress');
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

export async function getTeachMeOptions(guidelineId: string): Promise<TeachMeOptionsResponse> {
  const response = await apiFetch(`/sessions/teach-me-options?guideline_id=${guidelineId}`);
  if (!response.ok) throw new Error(`Failed to fetch teach-me options: ${response.statusText}`);
  return response.json();
}

export interface CardProgressResponse {
  session_id: string;
  phase: string;
  card_idx: number;
  is_complete: boolean;
  // Populated only when mark_complete=true triggers session finalization.
  concepts_covered?: string[];
  coverage?: number;
  guideline_id?: string | null;
}

export async function postCardProgress(
  sessionId: string,
  payload: CardProgressRequest,
): Promise<CardProgressResponse> {
  const response = await apiFetch(`/sessions/${sessionId}/card-progress`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to post card progress: ${response.statusText}`);
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

export async function getSessionReplay(sessionId: string): Promise<any> {
  const response = await apiFetch(`/sessions/${sessionId}/replay`);
  if (!response.ok) throw new Error(`Failed to fetch session replay: ${response.statusText}`);
  return response.json();
}

// ──────────────────────────────────────────────
// Guideline sessions
// ──────────────────────────────────────────────

export interface GuidelineSessionEntry {
  session_id: string;
  mode: string;
  teach_me_mode?: TeachMeMode | null;
  created_at: string | null;
  is_complete: boolean;
  coverage: number | null;
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

// ──────────────────────────────────────────────
// Kid Enrichment Profile & Personality
// ──────────────────────────────────────────────

export interface EnrichmentProfileResponse {
  interests: string[] | null;
  learning_styles: string[] | null;
  motivations: string[] | null;
  growth_areas: string[] | null;
  parent_notes: string | null;
  attention_span: string | null;
  pace_preference: string | null;
  personality_status: string | null;
  sections_filled: number;
  has_about_me: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface EnrichmentUpdateResponse {
  personality_status: string;
  sections_filled: number;
}

export interface PersonalityApiResponse {
  personality_json: Record<string, any> | null;
  tutor_brief: string | null;
  status: string;
  updated_at: string | null;
}

export async function getEnrichmentProfile(): Promise<EnrichmentProfileResponse> {
  const response = await apiFetch('/profile/enrichment');
  if (!response.ok) throw new Error(`Failed to fetch enrichment profile: ${response.statusText}`);
  return response.json();
}

export async function updateEnrichmentProfile(data: Record<string, any>): Promise<EnrichmentUpdateResponse> {
  const response = await apiFetch('/profile/enrichment', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error(`Failed to update enrichment profile: ${response.statusText}`);
  return response.json();
}

export async function getPersonality(): Promise<PersonalityApiResponse> {
  const response = await apiFetch('/profile/personality');
  if (!response.ok) throw new Error(`Failed to fetch personality: ${response.statusText}`);
  return response.json();
}

export async function regeneratePersonality(): Promise<void> {
  const response = await apiFetch('/profile/personality/regenerate', { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to regenerate personality: ${response.statusText}`);
}

// ──────────────────────────────────────────────
// Card phase actions (pre-computed explanations)
// ──────────────────────────────────────────────

export interface CheckInEventDTO {
  card_idx: number;
  card_title?: string;
  activity_type: string;
  wrong_count: number;
  hints_shown: number;
  confused_pairs: Array<{ left: string; right: string; wrong_count: number; wrong_picks?: string[] }>;
  auto_revealed: number;
}

export async function cardAction(
  sessionId: string,
  action: 'clear' | 'explain_differently',
  checkInEvents?: CheckInEventDTO[],
): Promise<any> {
  const payload: any = { action };
  if (checkInEvents && checkInEvents.length > 0) {
    payload.check_in_events = checkInEvents;
  }
  const response = await apiFetch(`/sessions/${sessionId}/card-action`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || response.statusText);
  }
  return response.json();
}

export async function simplifyCard(
  sessionId: string,
  cardIdx: number,
): Promise<any> {
  const response = await apiFetch(`/sessions/${sessionId}/simplify-card`, {
    method: 'POST',
    body: JSON.stringify({ card_idx: cardIdx }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || response.statusText);
  }
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

// ──────────────────────────────────────────────
// Text-to-speech
// ──────────────────────────────────────────────

export async function synthesizeSpeech(
  text: string,
  language: string = 'en',
  opts: { voiceRole?: 'tutor' | 'peer' } = {},
): Promise<Blob> {
  // Can't use apiFetch — it parses JSON, but we need a raw audio blob.
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (_accessToken) {
    headers['Authorization'] = `Bearer ${_accessToken}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  const body: Record<string, unknown> = { text, language };
  if (opts.voiceRole) body.voice_role = opts.voiceRole;

  const response = await fetch(`${API_BASE_URL}/text-to-speech`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
  }).finally(() => clearTimeout(timeout));

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Authentication required');
  }

  if (!response.ok) {
    throw new Error(`TTS failed: ${response.statusText}`);
  }

  return response.blob();
}

// ──────────────────────────────────────────────
// Issue reporting
// ──────────────────────────────────────────────

export async function uploadIssueScreenshot(file: File): Promise<string> {
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`;

  const res = await fetch(`${API_BASE_URL}/issues/upload-screenshot`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (res.status === 401) { window.location.href = '/login'; throw new Error('Auth required'); }
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  const data = await res.json();
  return data.s3_key;
}

export interface CreateIssueRequest {
  title: string;
  description: string;
  original_input: string;
  screenshot_s3_keys?: string[];
}

export interface IssueResponse {
  id: string;
  user_id: string | null;
  reporter_name: string | null;
  title: string;
  description: string;
  original_input: string | null;
  screenshot_s3_keys: string[] | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export async function createIssue(req: CreateIssueRequest): Promise<IssueResponse> {
  const res = await apiFetch('/issues', {
    method: 'POST',
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Create issue failed: ${res.statusText}`);
  return res.json();
}

export async function listIssues(statusFilter?: string): Promise<{ issues: IssueResponse[]; total: number }> {
  const params = statusFilter ? `?status_filter=${statusFilter}` : '';
  const res = await apiFetch(`/issues${params}`);
  if (!res.ok) throw new Error(`List issues failed: ${res.statusText}`);
  return res.json();
}

export async function getIssue(id: string): Promise<IssueResponse> {
  const res = await apiFetch(`/issues/${id}`);
  if (!res.ok) throw new Error(`Get issue failed: ${res.statusText}`);
  return res.json();
}

export async function updateIssueStatus(id: string, status: string): Promise<IssueResponse> {
  const res = await apiFetch(`/issues/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(`Update status failed: ${res.statusText}`);
  return res.json();
}

export async function getScreenshotUrl(issueId: string, s3Key: string): Promise<string> {
  const res = await apiFetch(`/issues/${issueId}/screenshots/${s3Key}`);
  if (!res.ok) throw new Error(`Get screenshot URL failed: ${res.statusText}`);
  const data = await res.json();
  return data.url;
}

// ──────────────────────────────────────────────
// WebSocket for streaming chat
// ──────────────────────────────────────────────

export interface TutorWSCallbacks {
  onToken: (text: string) => void;
  onAssistant: (message: string, audioText?: string | null, visualExplanation?: VisualExplanation | null, questionFormat?: QuestionFormat | null) => void;
  onVisualUpdate?: (visualExplanation: VisualExplanation) => void;
  onStateUpdate: (state: {
    session_id: string;
    current_step: number;
    total_steps: number;
    current_concept: string | null;
    progress_percentage: number;
    mastery_estimates: Record<string, number>;
    is_complete: boolean;
    mode: string;
    coverage: number;
    concepts_discussed: string[];
    is_paused: boolean;
  }) => void;
  onTyping: () => void;
  onError: (error: string) => void;
  onClose: () => void;
}

export class TutorWebSocket {
  private ws: WebSocket | null = null;
  private callbacks: TutorWSCallbacks;
  private url: string;
  private _connected = false;
  private _pendingMessages: string[] = [];

  constructor(sessionId: string, callbacks: TutorWSCallbacks) {
    this.callbacks = callbacks;
    const wsBase = API_BASE_URL.replace(/^http/, 'ws');
    const token = getAccessToken();
    this.url = `${wsBase}/sessions/ws/${sessionId}${token ? `?token=${token}` : ''}`;
  }

  connect(): void {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this._connected = true;
      // Flush any messages queued before connection
      for (const msg of this._pendingMessages) {
        this.ws!.send(msg);
      }
      this._pendingMessages = [];
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'token':
            this.callbacks.onToken(msg.payload?.message || '');
            break;
          case 'assistant':
            this.callbacks.onAssistant(
              msg.payload?.message || '',
              msg.payload?.audio_text,
              msg.payload?.visual_explanation,
              msg.payload?.question_format,
            );
            break;
          case 'state_update':
            if (msg.payload?.state) {
              this.callbacks.onStateUpdate(msg.payload.state);
            }
            break;
          case 'visual_update':
            if (msg.payload?.visual_explanation && this.callbacks.onVisualUpdate) {
              this.callbacks.onVisualUpdate(msg.payload.visual_explanation);
            }
            break;
          case 'typing':
            this.callbacks.onTyping();
            break;
          case 'error':
            this.callbacks.onError(msg.payload?.error || 'Unknown error');
            break;
        }
      } catch {
        // Ignore malformed messages
      }
    };

    this.ws.onerror = () => {
      this.callbacks.onError('WebSocket connection error');
    };

    this.ws.onclose = () => {
      this._connected = false;
      this.callbacks.onClose();
    };
  }

  sendChat(message: string): void {
    const payload = JSON.stringify({ type: 'chat', payload: { message } });
    if (this._connected && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload);
    } else {
      this._pendingMessages.push(payload);
    }
  }

  sendJson(data: Record<string, unknown>): void {
    const payload = JSON.stringify(data);
    if (this._connected && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload);
    }
  }

  disconnect(): void {
    this._connected = false;
    this.ws?.close();
    this.ws = null;
  }

  get isConnected(): boolean {
    return this._connected && this.ws?.readyState === WebSocket.OPEN;
  }
}


// ──────────────────────────────────────────────
// Practice v2 — client functions
// ──────────────────────────────────────────────

export interface PracticeAttemptQuestion {
  q_idx: number;
  q_id: string;
  format: string;
  difficulty: string;
  concept_tag: string;
  presentation_seed: number;
  question_json: Record<string, unknown>;
}

export interface PracticeAttempt {
  id: string;
  user_id: string;
  guideline_id: string;
  status: 'in_progress' | 'grading' | 'graded' | 'grading_failed';
  total_possible: number;
  questions: PracticeAttemptQuestion[];
  answers: Record<string, unknown>;
  created_at: string;
  submitted_at: string | null;
}

export interface GradedQuestion {
  q_idx: number;
  q_id: string;
  format: string;
  difficulty: string;
  concept_tag: string;
  question_json: Record<string, unknown>;
  student_answer: unknown;
  correct: boolean;
  score: number;
  correct_answer_summary: unknown;
  rationale: string | null;
  visual_explanation_code: string | null;
}

export interface PracticeAttemptResults {
  id: string;
  user_id: string;
  guideline_id: string;
  status: 'graded' | 'grading_failed';
  total_possible: number;
  total_score: number | null;
  questions: GradedQuestion[];
  grading_error: string | null;
  submitted_at: string | null;
  graded_at: string | null;
}

export interface PracticeAttemptSummary {
  id: string;
  status: string;
  total_score: number | null;
  total_possible: number;
  submitted_at: string | null;
  graded_at: string | null;
}

export interface PracticeAvailability {
  available: boolean;
  question_count: number;
}

export async function getPracticeAvailability(guidelineId: string): Promise<PracticeAvailability> {
  const r = await apiFetch(`/practice/availability/${guidelineId}`);
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function startPractice(guidelineId: string): Promise<PracticeAttempt> {
  const r = await apiFetch('/practice/start', {
    method: 'POST',
    body: JSON.stringify({ guideline_id: guidelineId }),
  });
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function getPracticeAttempt(
  attemptId: string,
): Promise<PracticeAttempt | PracticeAttemptResults> {
  const r = await apiFetch(`/practice/attempts/${attemptId}`);
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function savePracticeAnswer(
  attemptId: string,
  qIdx: number,
  answer: unknown,
  signal?: AbortSignal,
): Promise<void> {
  const r = await apiFetch(`/practice/attempts/${attemptId}/answer`, {
    method: 'PATCH',
    body: JSON.stringify({ q_idx: qIdx, answer }),
    signal,
  });
  if (!r.ok && r.status !== 204) {
    throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  }
}

export async function submitPractice(
  attemptId: string,
  finalAnswers: Record<string, unknown>,
): Promise<PracticeAttempt> {
  const r = await apiFetch(`/practice/attempts/${attemptId}/submit`, {
    method: 'POST',
    body: JSON.stringify({ final_answers: finalAnswers }),
  });
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function retryPracticeGrading(attemptId: string): Promise<void> {
  const r = await apiFetch(`/practice/attempts/${attemptId}/retry-grading`, {
    method: 'POST',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  }
}

export async function markPracticeViewed(attemptId: string): Promise<void> {
  const r = await apiFetch(`/practice/attempts/${attemptId}/mark-viewed`, {
    method: 'POST',
  });
  if (!r.ok && r.status !== 204) {
    throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  }
}

export async function listRecentPracticeAttempts(): Promise<{ attempts: PracticeAttemptSummary[] }> {
  const r = await apiFetch('/practice/attempts/recent');
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function listPracticeAttemptsForTopic(
  guidelineId: string,
): Promise<PracticeAttemptSummary[]> {
  const r = await apiFetch(`/practice/attempts/for-topic/${guidelineId}`);
  if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  return r.json();
}
