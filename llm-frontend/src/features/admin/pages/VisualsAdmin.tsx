import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, getVisualStatus, generateVisuals, getVisualJobStatus,
  getTopicExplanations, deleteVisuals, getVisualJobStageSnapshots,
  BookV2DetailResponse, TopicVisualStatusV2, ProcessingJobResponseV2,
  TopicExplanationsDetailResponseV2, ExplanationCardV2, VisualStageSnapshotV2,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

/* ─── Status Badge ─── */
const StatusBadge: React.FC<{ total: number; withVisuals: number; hasExplanations: boolean }> = ({ total, withVisuals, hasExplanations }) => {
  if (!hasExplanations) return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px', backgroundColor: '#F3F4F6', color: '#6B7280' }}>
      No Explanations
    </span>
  );
  if (total === 0) return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px', backgroundColor: '#F3F4F6', color: '#6B7280' }}>
      No Cards
    </span>
  );
  if (withVisuals === 0) return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px', backgroundColor: '#FEF3C7', color: '#92400E' }}>
      No Visuals
    </span>
  );
  if (withVisuals < total) return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px', backgroundColor: '#DBEAFE', color: '#1D4ED8' }}>
      {withVisuals}/{total} cards
    </span>
  );
  return (
    <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px', backgroundColor: '#D1FAE5', color: '#065F46' }}>
      All {total} cards
    </span>
  );
};

/* ─── Visual Card Viewer Modal ─── */
const VisualViewerModal: React.FC<{
  detail: TopicExplanationsDetailResponseV2;
  onClose: () => void;
}> = ({ detail, onClose }) => {
  const allCards: (ExplanationCardV2 & { visual_explanation?: { output_type?: string; title?: string; visual_summary?: string; pixi_code?: string } })[] =
    detail.variants.flatMap(v => v.cards_json as any[]);
  const cardsWithVisuals = allCards.filter(c => c.visual_explanation?.pixi_code);

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
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '16px' }}>{detail.topic_title}</div>
            <div style={{ fontSize: '12px', color: '#6B7280' }}>
              {cardsWithVisuals.length} card(s) with visuals out of {allCards.length} total
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          {cardsWithVisuals.length === 0 && (
            <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF' }}>No cards with visuals</div>
          )}
          {cardsWithVisuals.map((card, i) => (
            <div key={i} style={{ marginBottom: '16px', border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ padding: '10px 14px', backgroundColor: '#F9FAFB', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: '13px' }}>
                  {card.card_idx}. {card.title}
                </span>
                <span style={{
                  fontSize: '10px', fontWeight: 600, padding: '2px 6px', borderRadius: '8px',
                  backgroundColor: card.visual_explanation?.output_type === 'animated_visual' ? '#FEF3C7' : '#DBEAFE',
                  color: card.visual_explanation?.output_type === 'animated_visual' ? '#92400E' : '#1D4ED8',
                }}>
                  {card.visual_explanation?.output_type || 'visual'}
                </span>
              </div>
              {card.visual_explanation?.visual_summary && (
                <div style={{ padding: '8px 14px', fontSize: '12px', color: '#6B7280', borderBottom: '1px solid #E5E7EB' }}>
                  {card.visual_explanation.visual_summary}
                </div>
              )}
              <pre style={{
                margin: 0, padding: '12px 14px', fontSize: '11px', lineHeight: '1.4',
                overflow: 'auto', maxHeight: '300px', backgroundColor: '#1F2937', color: '#E5E7EB',
                fontFamily: 'monospace',
              }}>
                {card.visual_explanation?.pixi_code || 'No code'}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

/* ─── Main Page ─── */
export default function VisualsAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [topics, setTopics] = useState<TopicVisualStatusV2[]>([]);
  const [chapterJob, setChapterJob] = useState<ProcessingJobResponseV2 | null>(null);
  const [topicJobs, setTopicJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [viewingVisuals, setViewingVisuals] = useState<TopicExplanationsDetailResponseV2 | null>(null);
  const [viewingStages, setViewingStages] = useState<{ stages: VisualStageSnapshotV2[]; topicTitle: string } | null>(null);
  const [reviewRounds, setReviewRounds] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chapterPollRef = useRef<NodeJS.Timeout | null>(null);
  const topicPollRef = useRef<Record<string, NodeJS.Timeout>>({});

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, vsStatus] = await Promise.all([
        getBookV2(bookId),
        getVisualStatus(bookId, chapterId),
      ]);
      setBook(bookData);
      setTopics(vsStatus.topics || []);
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

  // Resume polling for active jobs
  useEffect(() => {
    if (!bookId || !chapterId || !topics.length) return;
    getVisualJobStatus(bookId, { chapterId }).then(job => {
      if (['pending', 'running'].includes(job.status)) {
        setChapterJob(job);
        startChapterPolling();
      }
    }).catch(() => {});
    topics.forEach(t => {
      getVisualJobStatus(bookId, { guidelineId: t.guideline_id }).then(job => {
        if (['pending', 'running'].includes(job.status)) {
          setTopicJobs(prev => ({ ...prev, [t.guideline_id]: job }));
          startTopicPolling(t.guideline_id);
        }
      }).catch(() => {});
    });
  }, [bookId, chapterId, topics.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const startChapterPolling = useCallback(() => {
    if (!bookId || !chapterId || chapterPollRef.current) return;
    const poll = async () => {
      try {
        const job = await getVisualJobStatus(bookId!, { chapterId });
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
        const job = await getVisualJobStatus(bookId!, { guidelineId });
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

  const handleGenerate = async (guidelineId?: string, force = false) => {
    if (!bookId || !chapterId) return;
    try {
      const fanOut = await generateVisuals(bookId, {
        chapterId: guidelineId ? undefined : chapterId,
        guidelineId,
        force,
        reviewRounds,
      });
      if (fanOut.launched === 0) {
        setError(
          fanOut.skipped_guidelines && fanOut.skipped_guidelines.length
            ? `All ${fanOut.skipped_guidelines.length} topic(s) already have a job in flight.`
            : 'Nothing to run.'
        );
        return;
      }
      const job = await getVisualJobStatus(
        bookId,
        guidelineId ? { guidelineId } : { chapterId },
      );
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

  const handleDeleteVisuals = async (guidelineId: string, title: string) => {
    if (!bookId) return;
    if (!confirm(`Delete all visuals for "${title}"?`)) return;
    try {
      await deleteVisuals(bookId, guidelineId);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleViewVisuals = async (guidelineId: string) => {
    if (!bookId) return;
    try {
      const detail = await getTopicExplanations(bookId, guidelineId);
      setViewingVisuals(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    }
  };

  const handleViewStages = async (guidelineId: string, topicTitle: string) => {
    if (!bookId) return;
    try {
      const job = topicJobs[guidelineId] || chapterJob;
      if (!job) {
        setError('No prior job found for this topic — run a generation first.');
        return;
      }
      const result = await getVisualJobStageSnapshots(bookId, job.job_id, guidelineId);
      if (!result.snapshots || result.snapshots.length === 0) {
        setError('No stage snapshots recorded for this topic. Re-run with review rounds ≥ 1.');
        return;
      }
      setViewingStages({ stages: result.snapshots, topicTitle });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stages');
    }
  };

  const getTopicStatus = (guidelineId: string): 'running' | 'idle' => {
    const topicJob = topicJobs[guidelineId];
    if (topicJob && ['pending', 'running'].includes(topicJob.status)) return 'running';
    if (chapterJob && ['pending', 'running'].includes(chapterJob.status)) return 'running';
    return 'idle';
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const isChapterRunning = chapterJob && ['pending', 'running'].includes(chapterJob.status);
  const totalVisuals = topics.reduce((s, t) => s + t.cards_with_visuals, 0);
  const totalCards = topics.reduce((s, t) => s + t.total_cards, 0);

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>Visual Enrichment</h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.title || chapter?.chapter_title || chapterId}
          &middot; {totalVisuals}/{totalCards} cards with visuals
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
        <button onClick={() => handleGenerate()} disabled={!!isChapterRunning} title="Generate visuals for cards that don't have them (skips existing)" style={{
          backgroundColor: '#8B5CF6', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isChapterRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isChapterRunning ? 0.6 : 1,
        }}>
          {isChapterRunning ? 'Running...' : 'Generate All'}
        </button>
        <button onClick={() => handleGenerate(undefined, true)} disabled={!!isChapterRunning} title="Force regenerate all visuals (overwrites existing)" style={{
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
            {[0, 1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
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
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 1fr 120px 250px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>#</span>
          <span>Topic</span>
          <span>Visuals</span>
          <span>Actions</span>
        </div>

        {topics.map((t, i) => {
          const topicRunning = getTopicStatus(t.guideline_id) === 'running';
          return (
            <div key={t.guideline_id} style={{
              display: 'grid', gridTemplateColumns: '40px 1fr 120px 250px',
              padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
              backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
            }}>
              <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{i + 1}</span>
              <span style={{ fontSize: '13px', fontWeight: 500 }}>{t.topic_title}</span>
              <StatusBadge total={t.total_cards} withVisuals={t.cards_with_visuals} hasExplanations={t.has_explanations} />
              {(t.layout_warning_count ?? 0) > 0 && (
                <span
                  title={`${t.layout_warning_count} card(s) have persistent layout overlap detected by the render harness`}
                  style={{
                    fontSize: '10px', fontWeight: 600, padding: '2px 6px',
                    borderRadius: '8px', backgroundColor: '#FEF3C7', color: '#92400E',
                  }}
                >
                  ⚠ {t.layout_warning_count} overlap
                </span>
              )}
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {t.has_explanations && (
                  <>
                    <button onClick={() => handleGenerate(t.guideline_id)} disabled={topicRunning} title="Generate visuals for this topic" style={actionBtn('#8B5CF6', topicRunning)}>
                      {topicRunning ? '...' : 'Generate'}
                    </button>
                    {t.cards_with_visuals > 0 && (
                      <>
                        <button onClick={() => handleGenerate(t.guideline_id, true)} disabled={topicRunning} title="Force regenerate visuals" style={actionBtn('#DC2626', topicRunning)}>
                          Force
                        </button>
                        <button onClick={() => handleViewVisuals(t.guideline_id)} title="View visual code" style={actionBtn('#0891B2', false)}>
                          View
                        </button>
                        <button onClick={() => handleViewStages(t.guideline_id, t.topic_title)} title="View per-round PixiJS snapshots from last job" style={actionBtn('#6366F1', false)}>
                          Stages
                        </button>
                        <button onClick={() => handleDeleteVisuals(t.guideline_id, t.topic_title)} title="Delete all visuals for this topic" style={actionBtn('#DC2626', false)}>
                          Delete
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}

        {topics.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            No approved topics with explanations in this chapter
          </div>
        )}
      </div>

      {/* Visual Viewer Modal */}
      {viewingVisuals && (
        <VisualViewerModal detail={viewingVisuals} onClose={() => setViewingVisuals(null)} />
      )}

      {/* Stages Viewer Modal */}
      {viewingStages && (
        <VisualStagesModal
          stages={viewingStages.stages}
          topicTitle={viewingStages.topicTitle}
          onClose={() => setViewingStages(null)}
        />
      )}
    </div>
  );
}

/* ─── Stages Viewer Modal ─── */
const VisualStagesModal: React.FC<{
  stages: VisualStageSnapshotV2[];
  topicTitle: string;
  onClose: () => void;
}> = ({ stages, topicTitle, onClose }) => {
  // Group by variant_key + card_idx so each card shows its progression
  const grouped = new Map<string, VisualStageSnapshotV2[]>();
  for (const s of stages) {
    const key = `${s.variant_key}__card${s.card_idx}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(s);
  }

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', justifyContent: 'center', alignItems: 'center',
    }} onClick={onClose}>
      <div style={{
        backgroundColor: 'white', borderRadius: '12px', width: '90%', maxWidth: '1000px',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
      }} onClick={e => e.stopPropagation()}>
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '16px' }}>{topicTitle}</div>
            <div style={{ fontSize: '12px', color: '#6B7280' }}>
              {grouped.size} card(s), {stages.length} snapshot(s)
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          {Array.from(grouped.entries()).map(([key, cardStages]) => (
            <div key={key} style={{ marginBottom: '20px', border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ padding: '10px 14px', backgroundColor: '#F9FAFB', fontWeight: 600, fontSize: '13px' }}>
                {cardStages[0].variant_key} · card {cardStages[0].card_idx} · {cardStages[0].output_type}
              </div>
              {cardStages.map((s, i) => (
                <div key={i} style={{ borderTop: '1px solid #E5E7EB' }}>
                  <div style={{ padding: '6px 14px', backgroundColor: '#F3F4F6', fontSize: '11px', color: '#374151', fontWeight: 600 }}>
                    {s.stage}
                  </div>
                  <pre style={{
                    margin: 0, padding: '10px 14px', fontSize: '11px',
                    backgroundColor: '#111827', color: '#E5E7EB',
                    overflow: 'auto', maxHeight: '300px', whiteSpace: 'pre-wrap',
                  }}>{s.pixi_code}</pre>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

/* ─── Helpers ─── */
function actionBtn(color: string, disabled: boolean): React.CSSProperties {
  return {
    backgroundColor: color, color: 'white', border: 'none',
    padding: '4px 10px', borderRadius: '4px', cursor: disabled ? 'wait' : 'pointer',
    fontSize: '11px', fontWeight: 600, opacity: disabled ? 0.5 : 1,
  };
}
