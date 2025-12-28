/**
 * Guidelines Review - Admin page for reviewing and approving teaching guidelines
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getGuidelineFilters,
  getAllGuidelinesForReview,
  approveGuideline,
  rejectGuideline,
  deleteGuideline,
  generateStudyPlan,
  getStudyPlan,
} from '../api/adminApi';
import { GuidelineReview, GuidelineFilters, StudyPlan } from '../types';

type StatusFilter = 'all' | 'TO_BE_REVIEWED' | 'APPROVED';

// Modal component for viewing study plan
const StudyPlanModal: React.FC<{
  plan: StudyPlan;
  guidelineTopic: string;
  guidelineSubtopic: string;
  onClose: () => void;
}> = ({ plan, guidelineTopic, guidelineSubtopic, onClose }) => {
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '20px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: 'white',
          borderRadius: '12px',
          maxWidth: '700px',
          width: '100%',
          maxHeight: '80vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid #E5E7EB',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>
              Study Plan
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#6B7280' }}>
              {guidelineTopic} / {guidelineSubtopic}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '24px',
              cursor: 'pointer',
              color: '#6B7280',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {/* Metadata */}
          <div
            style={{
              display: 'flex',
              gap: '16px',
              marginBottom: '20px',
              fontSize: '13px',
            }}
          >
            <span style={{ color: '#6B7280' }}>
              <strong>{plan.todo_list.length}</strong> steps
            </span>
            <span style={{ color: '#6B7280' }}>
              <strong>{plan.metadata.estimated_duration_minutes || '~15'}</strong> min
            </span>
            {plan.metadata.creative_theme && (
              <span style={{ color: '#8B5CF6' }}>
                Theme: {plan.metadata.creative_theme}
              </span>
            )}
          </div>

          {/* Steps */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {plan.todo_list.map((step, index) => (
              <div
                key={step.step_id}
                style={{
                  padding: '16px',
                  backgroundColor: '#F9FAFB',
                  borderRadius: '8px',
                  border: '1px solid #E5E7EB',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    marginBottom: '8px',
                  }}
                >
                  <span
                    style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '50%',
                      backgroundColor: '#4F46E5',
                      color: 'white',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '12px',
                      fontWeight: '600',
                    }}
                  >
                    {index + 1}
                  </span>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: '15px',
                      fontWeight: '600',
                      color: '#111827',
                    }}
                  >
                    {step.title}
                  </h3>
                </div>
                <p
                  style={{
                    margin: '0 0 10px',
                    fontSize: '14px',
                    color: '#4B5563',
                    lineHeight: '1.5',
                  }}
                >
                  {step.description}
                </p>
                <div
                  style={{
                    display: 'flex',
                    gap: '16px',
                    fontSize: '12px',
                  }}
                >
                  <span style={{ color: '#059669' }}>
                    <strong>Approach:</strong> {step.teaching_approach}
                  </span>
                </div>
                <div
                  style={{
                    marginTop: '8px',
                    padding: '8px 10px',
                    backgroundColor: '#EEF2FF',
                    borderRadius: '6px',
                    fontSize: '12px',
                    color: '#4338CA',
                  }}
                >
                  <strong>Success:</strong> {step.success_criteria}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '16px 24px',
            borderTop: '1px solid #E5E7EB',
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '8px 16px',
              backgroundColor: '#4F46E5',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

const GuidelinesReviewPage: React.FC = () => {
  const navigate = useNavigate();
  const [guidelines, setGuidelines] = useState<GuidelineReview[]>([]);
  const [filterOptions, setFilterOptions] = useState<GuidelineFilters | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [countryFilter, setCountryFilter] = useState<string>('');
  const [boardFilter, setBoardFilter] = useState<string>('');
  const [gradeFilter, setGradeFilter] = useState<string>('');
  const [subjectFilter, setSubjectFilter] = useState<string>('');

  // Expanded guideline for viewing full content
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Study plan modal state
  const [viewingPlan, setViewingPlan] = useState<{
    plan: StudyPlan;
    topic: string;
    subtopic: string;
  } | null>(null);

  // Track which guidelines have study plans (by id)
  const [studyPlanIds, setStudyPlanIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadFilterOptions();
  }, []);

  useEffect(() => {
    loadGuidelines();
  }, [statusFilter, countryFilter, boardFilter, gradeFilter, subjectFilter]);

  const loadFilterOptions = async () => {
    try {
      const options = await getGuidelineFilters();
      setFilterOptions(options);
    } catch (err) {
      console.error('Failed to load filter options:', err);
    }
  };

  const loadGuidelines = async () => {
    try {
      setLoading(true);
      setError(null);
      const filters: {
        country?: string;
        board?: string;
        grade?: number;
        subject?: string;
        status?: 'TO_BE_REVIEWED' | 'APPROVED';
      } = {};

      if (statusFilter !== 'all') filters.status = statusFilter;
      if (countryFilter) filters.country = countryFilter;
      if (boardFilter) filters.board = boardFilter;
      if (gradeFilter) filters.grade = parseInt(gradeFilter);
      if (subjectFilter) filters.subject = subjectFilter;

      const data = await getAllGuidelinesForReview(filters);
      setGuidelines(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load guidelines');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (guidelineId: string) => {
    setActionLoading(guidelineId);
    try {
      await approveGuideline(guidelineId);
      // Refresh guidelines and filter options
      await Promise.all([loadGuidelines(), loadFilterOptions()]);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to approve guideline');
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (guidelineId: string) => {
    setActionLoading(guidelineId);
    try {
      await rejectGuideline(guidelineId);
      // Refresh guidelines and filter options
      await Promise.all([loadGuidelines(), loadFilterOptions()]);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to reject guideline');
    } finally {
      setActionLoading(null);
    }
  };

  const handleGeneratePlan = async (guidelineId: string, guideline: GuidelineReview) => {
    setActionLoading(guidelineId);
    try {
      const plan = await generateStudyPlan(guidelineId, true); // Force regenerate for now
      // Add to tracked study plans
      setStudyPlanIds(prev => new Set(prev).add(guidelineId));
      // Show the plan immediately
      setViewingPlan({
        plan,
        topic: guideline.topic,
        subtopic: guideline.subtopic,
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to generate study plan');
    } finally {
      setActionLoading(null);
    }
  };

  const handleViewPlan = async (guidelineId: string, guideline: GuidelineReview) => {
    setActionLoading(guidelineId);
    try {
      const plan = await getStudyPlan(guidelineId);
      setStudyPlanIds(prev => new Set(prev).add(guidelineId));
      setViewingPlan({
        plan,
        topic: guideline.topic,
        subtopic: guideline.subtopic,
      });
    } catch (err) {
      // If no plan exists, offer to generate one
      if (confirm('No study plan found. Would you like to generate one?')) {
        await handleGeneratePlan(guidelineId, guideline);
      }
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (guidelineId: string) => {
    if (!confirm('Are you sure you want to delete this guideline? This action cannot be undone.')) {
      return;
    }
    setActionLoading(guidelineId);
    try {
      await deleteGuideline(guidelineId);
      // Refresh guidelines and filter options
      await Promise.all([loadGuidelines(), loadFilterOptions()]);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete guideline');
    } finally {
      setActionLoading(null);
    }
  };

  const handleApproveAll = async () => {
    const pendingGuidelines = guidelines.filter(g => g.review_status === 'TO_BE_REVIEWED');
    if (pendingGuidelines.length === 0) {
      alert('No pending guidelines to approve');
      return;
    }

    if (!confirm(`Approve all ${pendingGuidelines.length} pending guidelines?`)) {
      return;
    }

    setActionLoading('bulk');
    try {
      for (const guideline of pendingGuidelines) {
        await approveGuideline(guideline.id);
      }
      await Promise.all([loadGuidelines(), loadFilterOptions()]);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to approve guidelines');
    } finally {
      setActionLoading(null);
    }
  };

  const pendingCount = guidelines.filter(g => g.review_status === 'TO_BE_REVIEWED').length;

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
          <button
            onClick={() => navigate('/admin/books')}
            style={{
              padding: '6px 12px',
              backgroundColor: 'white',
              color: '#374151',
              border: '1px solid #D1D5DB',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            ← Books
          </button>
          <h1 style={{ fontSize: '28px', fontWeight: '600', margin: 0 }}>
            Guidelines Review
          </h1>
        </div>
        <p style={{ color: '#6B7280', margin: 0 }}>
          Review and approve teaching guidelines before they appear in the tutor workflow
        </p>
        {filterOptions && (
          <div style={{ marginTop: '8px', display: 'flex', gap: '16px', fontSize: '14px' }}>
            <span style={{ color: '#059669', fontWeight: '500' }}>
              {filterOptions.counts.approved} approved
            </span>
            <span style={{ color: '#D97706', fontWeight: '500' }}>
              {filterOptions.counts.pending} pending
            </span>
            <span style={{ color: '#6B7280' }}>
              {filterOptions.counts.total} total
            </span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div
        style={{
          marginBottom: '20px',
          padding: '16px',
          backgroundColor: '#F9FAFB',
          borderRadius: '8px',
          border: '1px solid #E5E7EB',
        }}
      >
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <label style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}>
              Status
            </label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              style={{
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid #D1D5DB',
                backgroundColor: 'white',
                fontSize: '14px',
                minWidth: '140px',
              }}
            >
              <option value="TO_BE_REVIEWED">Pending Review</option>
              <option value="APPROVED">Approved</option>
              <option value="all">All</option>
            </select>
          </div>

          {filterOptions && (
            <>
              <div>
                <label style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}>
                  Country
                </label>
                <select
                  value={countryFilter}
                  onChange={(e) => setCountryFilter(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    backgroundColor: 'white',
                    fontSize: '14px',
                    minWidth: '120px',
                  }}
                >
                  <option value="">All Countries</option>
                  {filterOptions.countries.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}>
                  Board
                </label>
                <select
                  value={boardFilter}
                  onChange={(e) => setBoardFilter(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    backgroundColor: 'white',
                    fontSize: '14px',
                    minWidth: '120px',
                  }}
                >
                  <option value="">All Boards</option>
                  {filterOptions.boards.map((b) => (
                    <option key={b} value={b}>{b}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}>
                  Grade
                </label>
                <select
                  value={gradeFilter}
                  onChange={(e) => setGradeFilter(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    backgroundColor: 'white',
                    fontSize: '14px',
                    minWidth: '100px',
                  }}
                >
                  <option value="">All Grades</option>
                  {filterOptions.grades.map((g) => (
                    <option key={g} value={g}>Grade {g}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}>
                  Subject
                </label>
                <select
                  value={subjectFilter}
                  onChange={(e) => setSubjectFilter(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    backgroundColor: 'white',
                    fontSize: '14px',
                    minWidth: '140px',
                  }}
                >
                  <option value="">All Subjects</option>
                  {filterOptions.subjects.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
            {pendingCount > 0 && statusFilter !== 'APPROVED' && (
              <button
                onClick={handleApproveAll}
                disabled={actionLoading === 'bulk'}
                style={{
                  padding: '8px 16px',
                  backgroundColor: '#10B981',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: actionLoading === 'bulk' ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: '500',
                  opacity: actionLoading === 'bulk' ? 0.6 : 1,
                }}
              >
                {actionLoading === 'bulk' ? 'Approving...' : `Approve All (${pendingCount})`}
              </button>
            )}
            <button
              onClick={loadGuidelines}
              style={{
                padding: '8px 16px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          <p>Loading guidelines...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div
          style={{
            padding: '15px',
            backgroundColor: '#FEE2E2',
            color: '#991B1B',
            borderRadius: '6px',
            marginBottom: '20px',
          }}
        >
          {error}
        </div>
      )}

      {/* Guidelines List */}
      {!loading && !error && (
        <div>
          {guidelines.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '60px 20px',
                backgroundColor: '#F9FAFB',
                borderRadius: '8px',
                border: '2px dashed #D1D5DB',
              }}
            >
              <p style={{ fontSize: '18px', color: '#6B7280', marginBottom: '10px' }}>
                {statusFilter === 'TO_BE_REVIEWED'
                  ? 'No pending guidelines to review'
                  : 'No guidelines found'}
              </p>
              <p style={{ color: '#9CA3AF' }}>
                {statusFilter === 'TO_BE_REVIEWED'
                  ? 'All guidelines have been reviewed!'
                  : 'Try adjusting your filters'}
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {guidelines.map((guideline) => {
                const isExpanded = expandedId === guideline.id;

                return (
                  <div
                    key={guideline.id}
                    style={{
                      backgroundColor: 'white',
                      border: '1px solid #E5E7EB',
                      borderRadius: '8px',
                      overflow: 'hidden',
                    }}
                  >
                    {/* Guideline Header */}
                    <div
                      style={{
                        padding: '16px',
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'space-between',
                        gap: '16px',
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        {/* Meta info */}
                        <div style={{ fontSize: '12px', color: '#6B7280', marginBottom: '6px' }}>
                          {guideline.country} • {guideline.board} • Grade {guideline.grade} • {guideline.subject}
                        </div>
                        {/* Topic & Subtopic */}
                        <div style={{ fontSize: '15px', fontWeight: '600', marginBottom: '4px' }}>
                          {guideline.topic}
                        </div>
                        <div style={{ fontSize: '14px', color: '#4B5563', marginBottom: '8px' }}>
                          {guideline.subtopic}
                        </div>
                        {/* Preview */}
                        <div
                          onClick={() => setExpandedId(isExpanded ? null : guideline.id)}
                          style={{
                            fontSize: '13px',
                            color: '#6B7280',
                            lineHeight: '1.5',
                            cursor: 'pointer',
                          }}
                        >
                          {isExpanded ? (
                            <div style={{ whiteSpace: 'pre-wrap' }}>{guideline.guideline}</div>
                          ) : (
                            <>
                              {guideline.guideline.substring(0, 200)}
                              {guideline.guideline.length > 200 && (
                                <span style={{ color: '#3B82F6' }}> ...click to expand</span>
                              )}
                            </>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexShrink: 0 }}>
                        <button
                          onClick={() => handleViewPlan(guideline.id, guideline)}
                          disabled={actionLoading === guideline.id}
                          style={{
                            padding: '6px 12px',
                            backgroundColor: '#4F46E5',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: actionLoading === guideline.id ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            opacity: actionLoading === guideline.id ? 0.6 : 1,
                          }}
                        >
                          {actionLoading === guideline.id ? '...' : 'View Plan'}
                        </button>
                        <button
                          onClick={() => handleGeneratePlan(guideline.id, guideline)}
                          disabled={actionLoading === guideline.id}
                          style={{
                            padding: '6px 12px',
                            backgroundColor: 'white',
                            color: '#4F46E5',
                            border: '1px solid #C7D2FE',
                            borderRadius: '6px',
                            cursor: actionLoading === guideline.id ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            opacity: actionLoading === guideline.id ? 0.6 : 1,
                          }}
                        >
                          {actionLoading === guideline.id ? '...' : 'Regenerate'}
                        </button>
                        {guideline.review_status === 'APPROVED' ? (
                          <>
                            <span
                              style={{
                                padding: '6px 12px',
                                backgroundColor: '#D1FAE5',
                                color: '#065F46',
                                borderRadius: '6px',
                                fontSize: '13px',
                                fontWeight: '500',
                              }}
                            >
                              Approved
                            </span>
                            <button
                              onClick={() => handleReject(guideline.id)}
                              disabled={actionLoading === guideline.id}
                              style={{
                                padding: '6px 12px',
                                backgroundColor: 'white',
                                color: '#6B7280',
                                border: '1px solid #D1D5DB',
                                borderRadius: '6px',
                                cursor: actionLoading === guideline.id ? 'not-allowed' : 'pointer',
                                fontSize: '13px',
                                opacity: actionLoading === guideline.id ? 0.6 : 1,
                              }}
                            >
                              Undo
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => handleApprove(guideline.id)}
                              disabled={actionLoading === guideline.id}
                              style={{
                                padding: '6px 14px',
                                backgroundColor: '#10B981',
                                color: 'white',
                                border: 'none',
                                borderRadius: '6px',
                                cursor: actionLoading === guideline.id ? 'not-allowed' : 'pointer',
                                fontSize: '13px',
                                fontWeight: '500',
                                opacity: actionLoading === guideline.id ? 0.6 : 1,
                              }}
                            >
                              {actionLoading === guideline.id ? '...' : 'Approve'}
                            </button>
                            <span
                              style={{
                                padding: '6px 12px',
                                backgroundColor: '#FEF3C7',
                                color: '#92400E',
                                borderRadius: '6px',
                                fontSize: '13px',
                              }}
                            >
                              Pending
                            </span>
                          </>
                        )}
                        <button
                          onClick={() => handleDelete(guideline.id)}
                          disabled={actionLoading === guideline.id}
                          style={{
                            padding: '6px 12px',
                            backgroundColor: 'white',
                            color: '#DC2626',
                            border: '1px solid #FCA5A5',
                            borderRadius: '6px',
                            cursor: actionLoading === guideline.id ? 'not-allowed' : 'pointer',
                            fontSize: '13px',
                            opacity: actionLoading === guideline.id ? 0.6 : 1,
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Study Plan Modal */}
      {viewingPlan && (
        <StudyPlanModal
          plan={viewingPlan.plan}
          guidelineTopic={viewingPlan.topic}
          guidelineSubtopic={viewingPlan.subtopic}
          onClose={() => setViewingPlan(null)}
        />
      )}
    </div>
  );
};

export default GuidelinesReviewPage;
