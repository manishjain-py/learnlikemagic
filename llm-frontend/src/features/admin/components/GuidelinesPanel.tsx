/**
 * Guidelines Panel Component
 *
 * Displays generated guidelines for a book with options to:
 * - Generate guidelines
 * - View all subtopics
 * - Review individual subtopics
 * - Approve/reject guidelines
 */

import React, { useState, useEffect } from 'react';
import {
  generateGuidelines,
  getGuidelines,
  approveGuidelines,
  rejectGuidelines,
  finalizeGuidelines,
} from '../api/adminApi';
import { useJobPolling } from '../hooks/useJobPolling';
import {
  GuidelineSubtopic,
  GenerateGuidelinesRequest,
  JobStatus,
  JobProgressDetail,
} from '../types';

interface GuidelinesPanelProps {
  bookId: string;
  totalPages: number;
  onProcessedPagesChange?: (processedPages: Set<number>) => void;
}

// Info tooltip component
const InfoTooltip: React.FC<{ text: string }> = ({ text }) => {
  const [show, setShow] = useState(false);

  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', marginLeft: '6px' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span
        style={{
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          backgroundColor: '#E5E7EB',
          color: '#6B7280',
          fontSize: '11px',
          fontWeight: '600',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'help',
        }}
      >
        ?
      </span>
      {show && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '8px',
            padding: '12px 14px',
            backgroundColor: '#1F2937',
            color: 'white',
            borderRadius: '8px',
            fontSize: '13px',
            lineHeight: '1.5',
            width: '280px',
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          }}
        >
          {text}
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid #1F2937',
            }}
          />
        </div>
      )}
    </span>
  );
};

// Action button component with consistent styling
const ActionButton: React.FC<{
  onClick: () => void;
  disabled?: boolean;
  variant: 'primary' | 'success' | 'danger' | 'purple' | 'secondary';
  children: React.ReactNode;
  tooltip?: string;
}> = ({ onClick, disabled, variant, children, tooltip }) => {
  const baseStyles: React.CSSProperties = {
    padding: '10px 16px',
    borderRadius: '8px',
    fontSize: '14px',
    fontWeight: '500',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    border: 'none',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    transition: 'all 0.2s',
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    primary: { backgroundColor: '#3B82F6', color: 'white' },
    success: { backgroundColor: '#10B981', color: 'white' },
    danger: { backgroundColor: '#EF4444', color: 'white' },
    purple: { backgroundColor: '#8B5CF6', color: 'white' },
    secondary: { backgroundColor: 'white', color: '#374151', border: '1px solid #D1D5DB' },
  };

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center' }}>
      <button
        onClick={onClick}
        disabled={disabled}
        style={{ ...baseStyles, ...variantStyles[variant] }}
      >
        {children}
      </button>
      {tooltip && <InfoTooltip text={tooltip} />}
    </span>
  );
};

// Status badge component
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const styles: Record<string, React.CSSProperties> = {
    final: { backgroundColor: '#D1FAE5', color: '#065F46' },
    needs_review: { backgroundColor: '#FEE2E2', color: '#991B1B' },
    stable: { backgroundColor: '#DBEAFE', color: '#1E40AF' },
    open: { backgroundColor: '#FEF3C7', color: '#92400E' },
    default: { backgroundColor: '#F3F4F6', color: '#374151' },
  };

  const style = styles[status] || styles.default;

  return (
    <span
      style={{
        padding: '4px 10px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: '500',
        ...style,
      }}
    >
      {status}
    </span>
  );
};

// Progress bar component for active jobs
const JobProgressBar: React.FC<{ job: JobStatus; label: string }> = ({ job, label }) => {
  const total = job.total_items || 1;
  const done = job.completed_items;
  const pct = Math.round((done / total) * 100);
  let detail: JobProgressDetail | null = null;
  try {
    detail = job.progress_detail ? JSON.parse(job.progress_detail) : null;
  } catch { /* ignore */ }

  return (
    <div style={{ padding: '16px', backgroundColor: '#EFF6FF', borderRadius: '8px', border: '1px solid #BFDBFE', marginBottom: '16px' }}>
      <div style={{ fontSize: '14px', fontWeight: '600', color: '#1E40AF', marginBottom: '8px' }}>
        {label}
      </div>
      {/* Progress bar */}
      <div style={{ height: '8px', backgroundColor: '#DBEAFE', borderRadius: '4px', overflow: 'hidden', marginBottom: '12px' }}>
        <div style={{ height: '100%', width: `${pct}%`, backgroundColor: '#3B82F6', borderRadius: '4px', transition: 'width 0.3s' }} />
      </div>

      {/* Stats */}
      <div style={{ fontSize: '14px', color: '#1E40AF', fontWeight: '600', marginBottom: '4px' }}>
        {done}/{total} pages ({pct}%)
      </div>
      {job.current_item && (
        <div style={{ fontSize: '13px', color: '#6B7280' }}>
          Currently processing: Page {job.current_item}
        </div>
      )}
      {detail?.stats && (
        <div style={{ fontSize: '13px', color: '#6B7280', marginTop: '4px' }}>
          Subtopics: {detail.stats.subtopics_created} created, {detail.stats.subtopics_merged} merged
        </div>
      )}
      {job.failed_items > 0 && (
        <div style={{ fontSize: '13px', color: '#DC2626', marginTop: '4px' }}>
          {job.failed_items} page(s) had errors
        </div>
      )}

      <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '8px', fontStyle: 'italic' }}>
        You can leave this page - processing continues in the background.
      </div>
    </div>
  );
};

export const GuidelinesPanel: React.FC<GuidelinesPanelProps> = ({
  bookId,
  totalPages,
  onProcessedPagesChange,
}) => {
  const [guidelines, setGuidelines] = useState<GuidelineSubtopic[]>([]);
  const [processedPages, setProcessedPages] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubtopic, setSelectedSubtopic] = useState<GuidelineSubtopic | null>(null);

  // Job polling for extraction and finalization
  const { job: extractionJob, isPolling: isExtracting, startPolling: startExtractionPolling } = useJobPolling(bookId, 'extraction');
  const { job: finalizationJob, isPolling: isFinalizing, startPolling: startFinalizationPolling } = useJobPolling(bookId, 'finalization');

  // Derive UI state from jobs
  const generating = isExtracting || extractionJob?.status === 'pending';
  const finalizing = isFinalizing || finalizationJob?.status === 'pending';

  // Derive new-pages range from API-provided processedPages
  const maxProcessedPage = processedPages.size > 0 ? Math.max(...processedPages) : 0;
  const newPagesStart = maxProcessedPage + 1;
  const newPagesEnd = totalPages;
  const hasNewPages = guidelines.length > 0 && newPagesStart <= totalPages;
  const newPagesCount = hasNewPages ? newPagesEnd - newPagesStart + 1 : 0;

  // Notify parent of processed pages changes
  useEffect(() => {
    onProcessedPagesChange?.(processedPages);
  }, [processedPages, onProcessedPagesChange]);

  // Load guidelines on mount
  useEffect(() => {
    loadGuidelines();
  }, [bookId]);

  const loadGuidelines = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await getGuidelines(bookId);
      setGuidelines(response.guidelines);
      setProcessedPages(new Set(response.processed_pages));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load guidelines');
      setGuidelines([]);
      setProcessedPages(new Set());
    } finally {
      setLoading(false);
    }
  };

  // Reload guidelines when extraction or finalization completes
  useEffect(() => {
    if (extractionJob?.status === 'completed' || finalizationJob?.status === 'completed') {
      loadGuidelines();
    }
  }, [extractionJob?.status, finalizationJob?.status]);

  const handleGenerateGuidelines = async () => {
    setError(null);

    const request: GenerateGuidelinesRequest = {
      start_page: 1,
      end_page: totalPages,
      auto_sync_to_db: false,
    };

    try {
      const result = await generateGuidelines(bookId, request);
      if (result.job_id) {
        startExtractionPolling(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate guidelines');
    }
  };

  const handleGenerateNewPages = async () => {
    setError(null);

    const request: GenerateGuidelinesRequest = {
      start_page: newPagesStart,
      end_page: newPagesEnd,
      auto_sync_to_db: false,
    };

    try {
      const result = await generateGuidelines(bookId, request);
      if (result.job_id) {
        startExtractionPolling(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate guidelines');
    }
  };

  const handleResumeGuidelines = async () => {
    setError(null);
    try {
      const result = await generateGuidelines(bookId, { resume: true });
      if (result.job_id) {
        startExtractionPolling(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resume generation');
    }
  };

  const handleApproveGuidelines = async () => {
    if (!window.confirm('Approve all guidelines and sync to database? This will make them available in the tutor app.')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await approveGuidelines(bookId);
      alert(`Successfully synced ${response.synced_count} guidelines to database`);
      await loadGuidelines();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve guidelines');
    } finally {
      setLoading(false);
    }
  };

  const handleRejectGuidelines = async () => {
    if (!window.confirm('Delete all guidelines? This cannot be undone. You can regenerate them later.')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await rejectGuidelines(bookId);
      setGuidelines([]);
      setProcessedPages(new Set());
      setSelectedSubtopic(null);
      setGenerationStats(null);
      setFinalizeStats(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject guidelines');
    } finally {
      setLoading(false);
    }
  };

  const handleFinalizeGuidelines = async () => {
    setError(null);

    try {
      const result = await finalizeGuidelines(bookId, false);
      if (result.job_id) {
        startFinalizationPolling(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to finalize guidelines');
    }
  };

  const finalCount = guidelines.filter(g => g.status === 'final').length;
  const openCount = guidelines.filter(g => g.status === 'open').length;

  return (
    <div
      style={{
        padding: '24px',
        backgroundColor: 'white',
        borderRadius: '12px',
        border: '1px solid #E5E7EB',
        marginTop: '24px',
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
          <div>
            <h2 style={{ fontSize: '22px', fontWeight: '600', margin: 0, marginBottom: '8px' }}>
              Teaching Guidelines
            </h2>
            {guidelines.length > 0 && (
              <div style={{ display: 'flex', gap: '16px', fontSize: '14px' }}>
                <span style={{ color: '#059669' }}>{finalCount} finalized</span>
                <span style={{ color: '#D97706' }}>{openCount} open</span>
                <span style={{ color: '#6B7280' }}>{guidelines.length} total</span>
              </div>
            )}
          </div>
        </div>

        {/* Workflow Steps */}
        <div
          style={{
            display: 'flex',
            gap: '8px',
            padding: '16px',
            backgroundColor: '#F9FAFB',
            borderRadius: '8px',
            marginBottom: '16px',
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: '13px', color: '#6B7280', marginRight: '8px' }}>Workflow:</span>
          <span
            style={{
              padding: '4px 12px',
              backgroundColor: guidelines.length === 0 ? '#3B82F6' : '#D1FAE5',
              color: guidelines.length === 0 ? 'white' : '#065F46',
              borderRadius: '16px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            1. Generate
          </span>
          <span style={{ color: '#9CA3AF' }}>→</span>
          <span
            style={{
              padding: '4px 12px',
              backgroundColor: guidelines.length > 0 && openCount > 0 ? '#8B5CF6' : '#F3F4F6',
              color: guidelines.length > 0 && openCount > 0 ? 'white' : '#6B7280',
              borderRadius: '16px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            2. Refine
          </span>
          <span style={{ color: '#9CA3AF' }}>→</span>
          <span
            style={{
              padding: '4px 12px',
              backgroundColor: finalCount > 0 ? '#10B981' : '#F3F4F6',
              color: finalCount > 0 ? 'white' : '#6B7280',
              borderRadius: '16px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            3. Approve & Sync
          </span>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          {guidelines.length === 0 ? (
            <ActionButton
              onClick={handleGenerateGuidelines}
              disabled={generating || totalPages === 0}
              variant="primary"
              tooltip="Analyzes all approved pages using AI to extract topics, subtopics, and teaching guidelines. Creates structured content in S3 storage. This may take a few minutes depending on the number of pages."
            >
              {generating ? 'Generating...' : 'Generate Guidelines'}
            </ActionButton>
          ) : (
            <>
              {hasNewPages && (
                <ActionButton
                  onClick={handleGenerateNewPages}
                  disabled={generating || loading}
                  variant="primary"
                  tooltip={`Incrementally generates guidelines for pages ${newPagesStart}-${newPagesEnd} only. Existing guidelines from pages 1-${maxProcessedPage} are preserved and used as context for accurate topic continuity detection.`}
                >
                  {generating ? 'Generating...' : `Generate for New Pages (${newPagesStart}-${newPagesEnd})`}
                </ActionButton>
              )}

              <ActionButton
                onClick={handleFinalizeGuidelines}
                disabled={finalizing || loading}
                variant="purple"
                tooltip="Uses AI to improve topic and subtopic names for clarity and consistency. Merges duplicate or similar topics. Marks all guidelines as 'final' status. Run this before approving to get polished results."
              >
                {finalizing ? 'Refining...' : 'Refine & Consolidate'}
              </ActionButton>

              <ActionButton
                onClick={handleApproveGuidelines}
                disabled={loading}
                variant="success"
                tooltip="Copies all finalized guidelines to the main database. After this, guidelines become visible in the tutor app for teachers to use. Sets review_status to 'APPROVED' for each guideline."
              >
                Approve & Sync to DB
              </ActionButton>

              <ActionButton
                onClick={handleRejectGuidelines}
                disabled={loading}
                variant="danger"
                tooltip="Permanently deletes all generated guidelines from S3 storage. Does NOT affect the uploaded pages. You can regenerate guidelines afterward if needed."
              >
                Reject & Delete
              </ActionButton>

              <ActionButton
                onClick={handleGenerateGuidelines}
                disabled={generating || loading}
                variant="secondary"
                tooltip="Runs the extraction pipeline again from scratch for ALL pages. Useful if pages were updated or if you want to try different extraction settings."
              >
                {generating ? 'Regenerating...' : 'Regenerate All'}
              </ActionButton>
            </>
          )}
        </div>
      </div>

      {/* New pages available banner */}
      {hasNewPages && !generating && (
        <div
          style={{
            marginBottom: '16px',
            padding: '14px 16px',
            backgroundColor: '#FFF7ED',
            border: '1px solid #FED7AA',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <span style={{ fontSize: '18px' }}>📄</span>
          <div>
            <span style={{ fontSize: '14px', fontWeight: '500', color: '#9A3412' }}>
              {newPagesCount} new {newPagesCount === 1 ? 'page' : 'pages'} available
            </span>
            <span style={{ fontSize: '14px', color: '#C2410C' }}>
              {' '}— Pages {newPagesStart}-{newPagesEnd} have not been processed for guidelines yet.
            </span>
          </div>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div
          style={{
            marginBottom: '16px',
            padding: '14px 16px',
            backgroundColor: '#FEE2E2',
            border: '1px solid #FECACA',
            borderRadius: '8px',
            color: '#991B1B',
            fontSize: '14px',
          }}
        >
          {error}
        </div>
      )}

      {/* Extraction progress bar */}
      {extractionJob && (extractionJob.status === 'running' || extractionJob.status === 'pending') && (
        <JobProgressBar job={extractionJob} label="Guideline Generation" />
      )}

      {/* Extraction failed — show resume UI */}
      {extractionJob?.status === 'failed' && extractionJob.last_completed_item !== null && (
        <div
          style={{
            marginBottom: '16px',
            padding: '16px',
            backgroundColor: '#FEF2F2',
            border: '1px solid #FECACA',
            borderRadius: '8px',
          }}
        >
          <div style={{ fontSize: '14px', fontWeight: '600', color: '#991B1B', marginBottom: '8px' }}>
            Generation stopped at page {extractionJob.last_completed_item}/{extractionJob.total_items}
          </div>
          <div style={{ fontSize: '13px', color: '#991B1B', marginBottom: '12px' }}>
            {extractionJob.error_message}
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <ActionButton onClick={handleResumeGuidelines} variant="primary">
              Resume from Page {(extractionJob.last_completed_item || 0) + 1}
            </ActionButton>
            <ActionButton onClick={handleGenerateGuidelines} variant="secondary">
              Restart from Page 1
            </ActionButton>
          </div>
        </div>
      )}

      {/* Extraction completed */}
      {extractionJob?.status === 'completed' && (
        <div
          style={{
            marginBottom: '16px',
            padding: '16px',
            backgroundColor: '#EFF6FF',
            border: '1px solid #BFDBFE',
            borderRadius: '8px',
          }}
        >
          <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#1E40AF', marginBottom: '12px' }}>
            Generation Complete
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
            <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '6px', textAlign: 'center' }}>
              <div style={{ fontSize: '24px', fontWeight: '600', color: '#3B82F6' }}>{extractionJob.completed_items}</div>
              <div style={{ fontSize: '12px', color: '#6B7280' }}>Pages Processed</div>
            </div>
            {extractionJob.failed_items > 0 && (
              <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '6px', textAlign: 'center' }}>
                <div style={{ fontSize: '24px', fontWeight: '600', color: '#EF4444' }}>{extractionJob.failed_items}</div>
                <div style={{ fontSize: '12px', color: '#6B7280' }}>Failed</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Finalization progress bar */}
      {finalizationJob && (finalizationJob.status === 'running' || finalizationJob.status === 'pending') && (
        <JobProgressBar job={finalizationJob} label="Refining & Consolidating" />
      )}

      {/* Finalization completed */}
      {finalizationJob?.status === 'completed' && finalizationJob.progress_detail && (() => {
        try {
          const detail = JSON.parse(finalizationJob.progress_detail);
          return (
            <div
              style={{
                marginBottom: '16px',
                padding: '16px',
                backgroundColor: '#F5F3FF',
                border: '1px solid #DDD6FE',
                borderRadius: '8px',
              }}
            >
              <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#6D28D9', marginBottom: '12px' }}>
                Refinement Complete
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
                <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '6px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: '600', color: '#10B981' }}>{detail.subtopics_finalized || 0}</div>
                  <div style={{ fontSize: '12px', color: '#6B7280' }}>Finalized</div>
                </div>
                <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '6px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: '600', color: '#8B5CF6' }}>{detail.subtopics_renamed || 0}</div>
                  <div style={{ fontSize: '12px', color: '#6B7280' }}>Names Refined</div>
                </div>
                <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '6px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: '600', color: '#F59E0B' }}>{detail.duplicates_merged || 0}</div>
                  <div style={{ fontSize: '12px', color: '#6B7280' }}>Duplicates Merged</div>
                </div>
              </div>
            </div>
          );
        } catch {
          return null;
        }
      })()}

      {/* Loading state */}
      {loading && guidelines.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px', color: '#6B7280' }}>
          Loading guidelines...
        </div>
      )}

      {/* Empty state */}
      {!loading && !generating && guidelines.length === 0 && (
        <div
          style={{
            textAlign: 'center',
            padding: '48px 24px',
            backgroundColor: '#F9FAFB',
            borderRadius: '8px',
            border: '2px dashed #D1D5DB',
          }}
        >
          <div style={{ fontSize: '40px', marginBottom: '16px' }}>📚</div>
          <p style={{ fontSize: '16px', color: '#374151', marginBottom: '8px', fontWeight: '500' }}>
            No guidelines generated yet
          </p>
          <p style={{ fontSize: '14px', color: '#6B7280' }}>
            Click "Generate Guidelines" to extract teaching content from all {totalPages} pages
          </p>
        </div>
      )}

      {/* Guidelines list */}
      {guidelines.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
          {/* Left: Subtopics list */}
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '16px', color: '#374151' }}>
              Subtopics ({guidelines.length})
            </h3>
            <div style={{ maxHeight: '500px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {guidelines.map((guideline) => (
                <div
                  key={`${guideline.topic_key}-${guideline.subtopic_key}`}
                  onClick={() => setSelectedSubtopic(guideline)}
                  style={{
                    padding: '14px 16px',
                    border: selectedSubtopic?.subtopic_key === guideline.subtopic_key
                      ? '2px solid #3B82F6'
                      : '1px solid #E5E7EB',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    backgroundColor: selectedSubtopic?.subtopic_key === guideline.subtopic_key
                      ? '#EFF6FF'
                      : 'white',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                    <h4 style={{ fontSize: '14px', fontWeight: '600', margin: 0, color: '#1F2937' }}>
                      {guideline.subtopic_title}
                    </h4>
                    <StatusBadge status={guideline.status} />
                  </div>
                  <p style={{ fontSize: '13px', color: '#6B7280', margin: 0 }}>
                    {guideline.topic_title}
                  </p>
                  <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '8px' }}>
                    Pages {guideline.source_page_start}-{guideline.source_page_end}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Subtopic details */}
          <div
            style={{
              border: '1px solid #E5E7EB',
              borderRadius: '8px',
              padding: '20px',
              maxHeight: '560px',
              overflowY: 'auto',
              backgroundColor: '#FAFAFA',
            }}
          >
            {selectedSubtopic ? (
              <div>
                <div style={{ marginBottom: '16px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: '600', margin: 0, marginBottom: '8px', color: '#1F2937' }}>
                    {selectedSubtopic.subtopic_title}
                  </h3>
                  <p style={{ fontSize: '14px', color: '#6B7280', margin: 0 }}>
                    {selectedSubtopic.topic_title}
                  </p>
                </div>

                {/* V2: Single Guidelines Field */}
                {selectedSubtopic.guidelines && (
                  <div
                    style={{
                      padding: '16px',
                      backgroundColor: 'white',
                      border: '1px solid #E5E7EB',
                      borderRadius: '8px',
                      marginBottom: '16px',
                    }}
                  >
                    <h4 style={{ fontSize: '13px', fontWeight: '600', color: '#6B7280', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Teaching Guidelines
                    </h4>
                    <div style={{ fontSize: '14px', lineHeight: '1.7', color: '#374151', whiteSpace: 'pre-wrap' }}>
                      {selectedSubtopic.guidelines}
                    </div>
                  </div>
                )}

                {/* V1: Structured Fields (Backward Compatibility) */}
                {!selectedSubtopic.guidelines && selectedSubtopic.description && (
                  <div
                    style={{
                      padding: '16px',
                      backgroundColor: 'white',
                      border: '1px solid #E5E7EB',
                      borderRadius: '8px',
                      marginBottom: '16px',
                    }}
                  >
                    <h4 style={{ fontSize: '13px', fontWeight: '600', color: '#6B7280', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Overview
                    </h4>
                    <div style={{ fontSize: '14px', lineHeight: '1.7', color: '#374151', whiteSpace: 'pre-wrap' }}>
                      {selectedSubtopic.description}
                    </div>
                  </div>
                )}

                {/* Metadata */}
                <div
                  style={{
                    padding: '12px 16px',
                    backgroundColor: '#F3F4F6',
                    borderRadius: '8px',
                    fontSize: '13px',
                    color: '#6B7280',
                  }}
                >
                  <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                    <span>Pages: {selectedSubtopic.source_page_start}-{selectedSubtopic.source_page_end}</span>
                    <span>Version: {selectedSubtopic.version}</span>
                    <span>Status: {selectedSubtopic.status}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '60px 20px', color: '#9CA3AF' }}>
                <div style={{ fontSize: '32px', marginBottom: '12px' }}>👈</div>
                <p>Select a subtopic to view details</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
