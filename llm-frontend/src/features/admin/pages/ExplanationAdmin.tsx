import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, generateExplanations, getExplanationJobStatus,
  getExplanationStatus, getTopicExplanations, deleteExplanations,
  getJobStageSnapshots,
  BookV2DetailResponse, ProcessingJobResponseV2,
  TopicExplanationStatusV2, TopicExplanationsDetailResponseV2,
  ExplanationCardV2, StageSnapshotV2,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

/* ─── Card Renderer (reusable) ─── */
const CardList: React.FC<{ cards: ExplanationCardV2[] }> = ({ cards }) => (
  <div>
    {cards.map((card, ci) => (
      <div key={ci} style={{
        marginBottom: '8px', padding: '10px 14px',
        border: '1px solid #E5E7EB', borderRadius: '6px',
        backgroundColor: card.card_type === 'visual' ? '#FFFBEB' : 'white',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span style={{ fontWeight: 600, fontSize: '13px' }}>
            {card.card_idx}. {card.title}
          </span>
          <span style={{
            fontSize: '10px', fontWeight: 600, padding: '2px 6px', borderRadius: '8px',
            backgroundColor:
              card.card_type === 'concept' ? '#EDE9FE' :
              card.card_type === 'example' ? '#DBEAFE' :
              card.card_type === 'visual' ? '#FEF3C7' :
              card.card_type === 'analogy' ? '#D1FAE5' :
              card.card_type === 'check_in' ? '#CCFBF1' : '#F3F4F6',
            color:
              card.card_type === 'concept' ? '#5B21B6' :
              card.card_type === 'example' ? '#1D4ED8' :
              card.card_type === 'visual' ? '#92400E' :
              card.card_type === 'analogy' ? '#065F46' :
              card.card_type === 'check_in' ? '#115E59' : '#374151',
          }}>
            {card.card_type}
          </span>
        </div>
        <div style={{ fontSize: '13px', color: '#374151', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
          {card.content}
        </div>
        {card.visual && (
          <pre style={{
            marginTop: '8px', padding: '10px', backgroundColor: '#F9FAFB',
            border: '1px solid #E5E7EB', borderRadius: '4px', fontSize: '12px',
            lineHeight: '1.4', overflow: 'auto', fontFamily: 'monospace',
          }}>
            {card.visual}
          </pre>
        )}
      </div>
    ))}
  </div>
);

/* ─── Stage Viewer ─── */
const StageViewer: React.FC<{
  stages: StageSnapshotV2[];
  topicTitle: string;
  onClose: () => void;
}> = ({ stages, topicTitle, onClose }) => {
  const [activeStage, setActiveStage] = useState(0);

  if (!stages.length) return null;

  const stageLabels = stages.map(s => {
    if (s.stage === 'initial') return 'Initial';
    if (s.stage === 'existing') return 'Existing';
    return s.stage.replace('refine_', 'Refine ');
  });

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', justifyContent: 'center', alignItems: 'center',
    }} onClick={onClose}>
      <div style={{
        backgroundColor: 'white', borderRadius: '12px', width: '90%', maxWidth: '900px',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
      }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '16px' }}>Pipeline Stages: {topicTitle}</div>
            <div style={{ fontSize: '12px', color: '#6B7280' }}>{stages.length} stage(s)</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '0', borderBottom: '1px solid #E5E7EB' }}>
          {stageLabels.map((label, i) => (
            <button key={i} onClick={() => setActiveStage(i)} style={{
              padding: '10px 20px', border: 'none', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
              backgroundColor: i === activeStage ? 'white' : '#F9FAFB',
              color: i === activeStage ? '#5B21B6' : '#6B7280',
              borderBottom: i === activeStage ? '2px solid #5B21B6' : '2px solid transparent',
            }}>
              {label}
              <span style={{ fontSize: '11px', fontWeight: 400, marginLeft: '6px', color: '#9CA3AF' }}>
                ({stages[i].cards.length} cards)
              </span>
            </button>
          ))}
        </div>

        {/* Card content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          <CardList cards={stages[activeStage].cards} />
        </div>
      </div>
    </div>
  );
};

/* ─── Status Badge ─── */
const StatusBadge: React.FC<{ status: string; variantCount?: number }> = ({ status, variantCount }) => {
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    not_generated: { bg: '#F3F4F6', color: '#6B7280', label: 'Not Generated' },
    running: { bg: '#EDE9FE', color: '#5B21B6', label: 'Running...' },
    success: { bg: '#D1FAE5', color: '#065F46', label: variantCount ? `Generated (${variantCount})` : 'Generated' },
    failed: { bg: '#FEE2E2', color: '#991B1B', label: 'Failed' },
  };
  const c = cfg[status] || cfg.not_generated;
  return (
    <span style={{
      fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
      backgroundColor: c.bg, color: c.color,
    }}>{c.label}</span>
  );
};

/* ─── Main Page ─── */
export default function ExplanationAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [topics, setTopics] = useState<TopicExplanationStatusV2[]>([]);
  const [chapterJob, setChapterJob] = useState<ProcessingJobResponseV2 | null>(null);
  const [topicJobs, setTopicJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [viewingExpl, setViewingExpl] = useState<TopicExplanationsDetailResponseV2 | null>(null);
  const [viewingStages, setViewingStages] = useState<{ stages: StageSnapshotV2[]; topicTitle: string } | null>(null);
  const [reviewRounds, setReviewRounds] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chapterPollRef = useRef<NodeJS.Timeout | null>(null);
  const topicPollRef = useRef<Record<string, NodeJS.Timeout>>({});

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  // Load book + explanation status
  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, explStatus] = await Promise.all([
        getBookV2(bookId),
        getExplanationStatus(bookId, chapterId),
      ]);
      setBook(bookData);
      setTopics(explStatus.topics || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [bookId, chapterId]);

  useEffect(() => {
    loadData();
    return () => {
      if (chapterPollRef.current) clearInterval(chapterPollRef.current);
      Object.values(topicPollRef.current).forEach(clearInterval);
    };
  }, [loadData]);

  // On mount: check for any active jobs and resume polling
  useEffect(() => {
    if (!bookId || !chapterId || !topics.length) return;
    // Check chapter-level job
    getExplanationJobStatus(bookId, { chapterId }).then(job => {
      if (['pending', 'running'].includes(job.status)) {
        setChapterJob(job);
        startChapterPolling();
      }
    }).catch(() => {});
    // Check per-topic jobs
    topics.forEach(t => {
      getExplanationJobStatus(bookId, { guidelineId: t.guideline_id }).then(job => {
        if (['pending', 'running'].includes(job.status)) {
          setTopicJobs(prev => ({ ...prev, [t.guideline_id]: job }));
          startTopicPolling(t.guideline_id);
        }
      }).catch(() => {});
    });
  }, [bookId, chapterId, topics.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Polling
  const startChapterPolling = useCallback(() => {
    if (!bookId || !chapterId || chapterPollRef.current) return;
    const poll = async () => {
      try {
        const job = await getExplanationJobStatus(bookId!, { chapterId });
        setChapterJob(job);
        if (['completed', 'failed', 'completed_with_errors'].includes(job.status)) {
          if (chapterPollRef.current) { clearInterval(chapterPollRef.current); chapterPollRef.current = null; }
          loadData();
        }
      } catch { /* ignore */ }
    };
    poll();
    chapterPollRef.current = setInterval(poll, POLL_INTERVAL);
  }, [bookId, chapterId, loadData]);

  const startTopicPolling = useCallback((guidelineId: string) => {
    if (!bookId || topicPollRef.current[guidelineId]) return;
    const poll = async () => {
      try {
        const job = await getExplanationJobStatus(bookId!, { guidelineId });
        setTopicJobs(prev => ({ ...prev, [guidelineId]: job }));
        if (['completed', 'failed', 'completed_with_errors'].includes(job.status)) {
          clearInterval(topicPollRef.current[guidelineId]);
          delete topicPollRef.current[guidelineId];
          loadData();
        }
      } catch { /* ignore */ }
    };
    poll();
    topicPollRef.current[guidelineId] = setInterval(poll, POLL_INTERVAL);
  }, [bookId, loadData]);

  // Actions
  const handleGenerate = async (guidelineId?: string, mode = 'generate', force = false) => {
    if (!bookId || !chapterId) return;
    try {
      const job = await generateExplanations(bookId, {
        chapterId: guidelineId ? undefined : chapterId,
        guidelineId,
        force,
        mode,
        reviewRounds,
      });
      if (guidelineId) {
        setTopicJobs(prev => ({ ...prev, [guidelineId]: job }));
        startTopicPolling(guidelineId);
      } else {
        setChapterJob(job);
        startChapterPolling();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  };

  const handleDelete = async (guidelineId: string, title: string) => {
    if (!bookId) return;
    if (!confirm(`Delete explanations for "${title}"?`)) return;
    try {
      await deleteExplanations(bookId, { guidelineId });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleViewExplanations = async (guidelineId: string) => {
    if (!bookId) return;
    try {
      const detail = await getTopicExplanations(bookId, guidelineId);
      setViewingExpl(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    }
  };

  const handleViewStages = async (guidelineId: string, topicTitle: string) => {
    if (!bookId) return;
    // Find the latest completed job for this topic
    try {
      const job = await getExplanationJobStatus(bookId, { guidelineId });
      if (!job?.job_id) { setError('No job found for this topic'); return; }
      const result = await getJobStageSnapshots(bookId, job.job_id, guidelineId);
      if (!result.snapshots.length) { setError('No stage snapshots for this job'); return; }
      setViewingStages({ stages: result.snapshots, topicTitle });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stages');
    }
  };

  // Derive topic status
  const getTopicStatus = (guidelineId: string, variantCount: number): string => {
    const topicJob = topicJobs[guidelineId];
    const chapterRunning = chapterJob && ['pending', 'running'].includes(chapterJob.status);
    if (topicJob && ['pending', 'running'].includes(topicJob.status)) return 'running';
    if (chapterRunning) return 'running';
    if (variantCount > 0) return 'success';
    if (topicJob && topicJob.status === 'failed') return 'failed';
    return 'not_generated';
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const isChapterRunning = chapterJob && ['pending', 'running'].includes(chapterJob.status);

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>
          Explanation Generation
        </h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.chapter_title || chapterId}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ backgroundColor: '#FEE2E2', color: '#991B1B', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
          <button onClick={() => setError(null)} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      {/* Controls */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px',
        padding: '12px 16px', backgroundColor: '#F9FAFB', borderRadius: '8px',
      }}>
        <button onClick={() => handleGenerate()} disabled={!!isChapterRunning} title="Generate explanations for topics that don't have them yet (skips existing)" style={{
          backgroundColor: '#8B5CF6', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isChapterRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isChapterRunning ? 0.6 : 1,
        }}>
          {isChapterRunning ? 'Running...' : 'Generate All'}
        </button>
        <button onClick={() => handleGenerate(undefined, 'refine_only')} disabled={!!isChapterRunning} title="Keep existing cards and run review-refine rounds on them (no regeneration)" style={{
          backgroundColor: '#7C3AED', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isChapterRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isChapterRunning ? 0.6 : 1,
        }}>
          Refine All
        </button>
        <button onClick={() => handleGenerate(undefined, 'generate', true)} disabled={!!isChapterRunning} title="Delete all existing explanations and regenerate from scratch" style={{
          backgroundColor: '#DC2626', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isChapterRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isChapterRunning ? 0.6 : 1,
        }}>
          Force Regenerate All
        </button>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <label style={{ fontSize: '12px', color: '#6B7280' }}>Review rounds:</label>
          <select value={reviewRounds} onChange={e => setReviewRounds(Number(e.target.value))} style={{
            padding: '4px 8px', borderRadius: '4px', border: '1px solid #D1D5DB', fontSize: '13px',
          }}>
            {[0, 1, 2, 3].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      {/* Chapter job progress */}
      {isChapterRunning && chapterJob && (
        <div style={{
          padding: '10px 16px', backgroundColor: '#EDE9FE', borderRadius: '8px', marginBottom: '16px',
          display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px',
        }}>
          <span style={{ fontWeight: 600, color: '#5B21B6' }}>
            {chapterJob.current_item ? `Processing: ${chapterJob.current_item}` : 'Starting...'}
          </span>
          {chapterJob.total_items && (
            <span style={{ color: '#7C3AED' }}>
              {chapterJob.completed_items}/{chapterJob.total_items}
              {chapterJob.failed_items > 0 && ` (${chapterJob.failed_items} failed)`}
            </span>
          )}
        </div>
      )}

      {/* Topic list */}
      <div style={{ border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
        {/* Header row */}
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 1fr 100px 320px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>#</span>
          <span>Topic</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {topics.map((t, i) => {
          const topicStatus = getTopicStatus(t.guideline_id, t.variant_count);
          const topicRunning = topicStatus === 'running';

          return (
            <div key={t.guideline_id} style={{
              display: 'grid', gridTemplateColumns: '40px 1fr 100px 320px',
              padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
              backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
            }}>
              <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{i + 1}</span>
              <span style={{ fontSize: '13px', fontWeight: 500 }}>{t.topic_title}</span>
              <StatusBadge status={topicStatus} variantCount={t.variant_count} />
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button onClick={() => handleGenerate(t.guideline_id)} disabled={topicRunning} title="Generate explanation from scratch" style={actionBtn('#8B5CF6', topicRunning)}>
                  {topicRunning ? '...' : 'Generate'}
                </button>
                {t.variant_count > 0 && (
                  <>
                    <button onClick={() => handleGenerate(t.guideline_id, 'refine_only')} disabled={topicRunning} title="Run review-refine on existing cards" style={actionBtn('#7C3AED', topicRunning)}>
                      Refine
                    </button>
                    <button onClick={() => handleViewExplanations(t.guideline_id)} title="View current explanation cards" style={actionBtn('#2563EB', false)}>
                      View
                    </button>
                    <button onClick={() => handleViewStages(t.guideline_id, t.topic_title)} title="View pipeline stages from last job" style={actionBtn('#0891B2', false)}>
                      Stages
                    </button>
                    <button onClick={() => handleDelete(t.guideline_id, t.topic_title)} title="Delete all explanations for this topic" style={actionBtn('#DC2626', false)}>
                      Delete
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}

        {topics.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            No approved topics in this chapter
          </div>
        )}
      </div>

      {/* View Explanations Modal */}
      {viewingExpl && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
          display: 'flex', justifyContent: 'center', alignItems: 'center',
        }} onClick={() => setViewingExpl(null)}>
          <div style={{
            backgroundColor: 'white', borderRadius: '12px', width: '90%', maxWidth: '800px',
            maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div style={{ fontWeight: 700, fontSize: '16px' }}>{viewingExpl.topic_title}</div>
              <button onClick={() => setViewingExpl(null)} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
              {viewingExpl.variants.map(v => (
                <div key={v.variant_key} style={{ marginBottom: '16px' }}>
                  <div style={{
                    padding: '8px 12px', backgroundColor: '#F9FAFB', borderRadius: '6px', marginBottom: '8px',
                    fontSize: '13px', fontWeight: 600,
                  }}>
                    Variant {v.variant_key}: {v.variant_label} ({v.cards_json.length} cards)
                  </div>
                  <CardList cards={v.cards_json} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Stage Viewer Modal */}
      {viewingStages && (
        <StageViewer
          stages={viewingStages.stages}
          topicTitle={viewingStages.topicTitle}
          onClose={() => setViewingStages(null)}
        />
      )}
    </div>
  );
}

/* ─── Helpers ─── */
function actionBtn(color: string, disabled: boolean): React.CSSProperties {
  return {
    backgroundColor: color, color: 'white', border: 'none',
    padding: '4px 10px', borderRadius: '4px', cursor: disabled ? 'wait' : 'pointer',
    fontSize: '11px', fontWeight: 600, opacity: disabled ? 0.5 : 1,
  };
}
