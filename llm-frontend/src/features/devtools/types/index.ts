/**
 * TypeScript types for Dev Tools feature
 * Matches backend SessionState and AgentLogs responses
 */

// ===== Study Plan Types =====

export interface StudyPlanStep {
  step_id: number;
  type: 'explain' | 'check' | 'practice';
  concept: string;
  content_hint: string | null;
  question_type: 'conceptual' | 'procedural' | 'application' | null;
  question_count: number | null;
}

export interface StudyPlan {
  steps: StudyPlanStep[];
}

// ===== Guidelines Types =====

export interface TopicGuidelines {
  learning_objectives: string[];
  required_depth: string;
  prerequisite_concepts: string[];
  common_misconceptions: string[];
  teaching_approach: string;
}

// ===== Topic =====

export interface TopicData {
  topic_id: string;
  topic_name: string;
  subject: string;
  grade_level: number;
  guidelines: TopicGuidelines;
  study_plan: StudyPlan;
}

// ===== Misconception =====

export interface Misconception {
  concept: string;
  description: string;
  detected_at: string;
  resolved: boolean;
}

// ===== Session State Response =====

export interface SessionStateResponse {
  session_id: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  topic: TopicData | null;
  current_step: number;
  concepts_covered: string[];
  last_concept_taught: string | null;
  mastery_estimates: Record<string, number>;
  misconceptions: Misconception[];
  weak_areas: string[];
  is_complete?: boolean;
}

// ===== Agent Log Types =====

export interface AgentLogEntry {
  timestamp: string;
  turn_id: string;
  agent_name: string;
  event_type: string;
  input_summary: string | null;
  output: Record<string, unknown> | null;
  reasoning: string | null;
  duration_ms: number | null;
  prompt: string | null;
  model: string | null;
}

export interface AgentLogsResponse {
  session_id: string;
  turn_id: string | null;
  logs: AgentLogEntry[];
  total_count: number;
}
