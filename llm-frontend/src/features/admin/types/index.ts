/**
 * TypeScript types for Admin feature
 */

export interface Book {
  id: string;
  title: string;
  author: string | null;
  edition: string | null;
  edition_year: number | null;
  country: string;
  board: string;
  grade: number;
  subject: string;
  cover_image_s3_key: string | null;
  s3_prefix: string;

  // Counts for derived status
  page_count: number;
  guideline_count: number;
  approved_guideline_count: number;
  has_active_job: boolean;

  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface BookDetail extends Book {
  pages: PageInfo[];
}

export interface PageInfo {
  page_num: number;
  image_s3_key: string;
  text_s3_key: string;
  status: 'pending_review' | 'approved';
  approved_at: string | null;
}

export interface CreateBookRequest {
  title: string;
  author?: string;
  edition?: string;
  edition_year?: number;
  country: string;
  board: string;
  grade: number;
  subject: string;
}

export interface PageUploadResponse {
  page_num: number;
  image_url: string;
  ocr_text: string;
  status: string;
}

export interface PageDetails {
  page_num: number;
  status: string;
  image_url: string;
  text_url: string;
  ocr_text: string;
}



// ===== Phase 6 Guideline Types =====

export interface Assessment {
  level: 'basic' | 'proficient' | 'advanced';
  prompt: string;
  answer: string;
}

export interface GuidelineSubtopic {
  topic_key: string;
  topic_title: string;
  subtopic_key: string;
  subtopic_title: string;
  status: 'open' | 'stable' | 'final' | 'needs_review';
  source_page_start: number;
  source_page_end: number;
  version: number;

  // V2 field (primary)
  guidelines?: string;  // V2: Single comprehensive guidelines field

  // V1 fields (optional for backward compatibility)
  objectives?: string[];
  examples?: string[];
  misconceptions?: string[];
  assessments?: Assessment[];
  teaching_description?: string | null;
  description?: string | null;
  evidence_summary?: string;
  confidence?: number;
  quality_score?: number | null;
}

export interface GuidelinesListResponse {
  book_id: string;
  total_subtopics: number;
  guidelines: GuidelineSubtopic[];
}

export interface GenerateGuidelinesRequest {
  start_page?: number;
  end_page?: number;
  auto_sync_to_db?: boolean;
  version?: 'v1' | 'v2';  // V2: Version selection (defaults to v2)
}

export interface GenerateGuidelinesResponse {
  book_id: string;
  status: string;
  pages_processed: number;
  subtopics_created: number;
  subtopics_merged?: number;  // V2: Number of merge operations
  subtopics_finalized: number;
  duplicates_merged?: number;  // V2: Number of duplicates merged
  errors: string[];
  warnings: string[];
}

// ===== Guidelines Review Types =====

export interface GuidelineReview {
  id: string;
  country: string;
  board: string;
  grade: number;
  subject: string;
  topic: string;
  subtopic: string;
  guideline: string;
  review_status: 'TO_BE_REVIEWED' | 'APPROVED';
  updated_at: string;
}

export interface GuidelineFilters {
  countries: string[];
  boards: string[];
  grades: number[];
  subjects: string[];
  counts: {
    total: number;
    pending: number;
    approved: number;
  };
}
