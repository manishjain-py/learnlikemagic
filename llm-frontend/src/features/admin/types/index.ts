/**
 * TypeScript types for Admin feature
 */

// ===== Evaluation Types =====

export interface EvalRunSummary {
  run_id: string;
  timestamp: string;
  topic_id: string;
  message_count: number;
  avg_score: number | null;
  scores: Record<string, number>;
  source?: string;
  source_session_id?: string;
}

export interface EvalMessage {
  role: string;
  content: string;
  turn: number;
  timestamp: string;
}

export interface EvalProblem {
  title: string;
  turns: number[];
  description: string;
  quote: string;
  severity: string;
  root_cause: string;
}

export interface EvalResult {
  scores: Record<string, number>;
  dimension_analysis: Record<string, string>;
  problems: EvalProblem[];
  summary?: string;
  avg_score: number;
}

export interface EvalRunDetail {
  run_id: string;
  config: Record<string, any>;
  messages: EvalMessage[];
  message_count: number;
  evaluation: EvalResult | null;
}

export interface EvalStatus {
  status: string;
  run_id: string | null;
  detail: string;
  turn: number;
  max_turns: number;
  error: string | null;
}

export interface StartEvalRequest {
  topic_id: string;
  persona_file?: string;
  max_turns?: number;
}

export interface SessionSummary {
  session_id: string;
  created_at: string | null;
  topic_name: string | null;
  message_count: number;
  mastery: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
}

export interface EvaluateSessionRequest {
  session_id: string;
}

// ===== Guidelines Review Types (used by Evaluation) =====

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

// ===== LLM Config Types =====

export type ReasoningEffort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export const REASONING_EFFORT_OPTIONS: ReasoningEffort[] = [
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
];

export interface LLMConfig {
  component_key: string;
  provider: string;
  model_id: string;
  reasoning_effort: ReasoningEffort;
  description: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface LLMConfigOptions {
  [provider: string]: string[];
}

// ===== Feature Flag Types =====

export interface FeatureFlag {
  flag_name: string;
  enabled: boolean;
  description: string | null;
  updated_at: string | null;
  updated_by: string | null;
}
