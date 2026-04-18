import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, getChapterTopics, getTopicDetail, deleteTopic,
  startProcessing, reprocessChapter, refinalizeChapter,
  getLatestJobV2,
  BookV2DetailResponse, ChapterTopicResponseV2, ProcessingJobResponseV2,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

/* ─── Status Badge ─── */
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    draft: { bg: '#F3F4F6', color: '#6B7280', label: 'Draft' },
    consolidated: { bg: '#FEF3C7', color: '#92400E', label: 'Consolidated' },
    final: { bg: '#DBEAFE', color: '#1D4ED8', label: 'Final' },
    approved: { bg: '#D1FAE5', color: '#065F46', label: 'Approved' },
  };
  const c = cfg[status] || { bg: '#F3F4F6', color: '#6B7280', label: status };
  return (
    <span style={{
      fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
      backgroundColor: c.bg, color: c.color,
    }}>{c.label}</span>
  );
};

/* ─── Topic Detail Modal ─── */
const TopicModal: React.FC<{
  topic: ChapterTopicResponseV2;
  onClose: () => void;
}> = ({ topic, onClose }) => (
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
          <div style={{ fontWeight: 700, fontSize: '16px' }}>{topic.topic_title}</div>
          <div style={{ fontSize: '12px', color: '#6B7280', marginTop: '2px' }}>
            {topic.topic_key}
            {topic.source_page_start && ` · Pages ${topic.source_page_start}–${topic.source_page_end || '?'}`}
            {topic.sequence_order != null && ` · Order: ${topic.sequence_order}`}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <StatusBadge status={topic.status} />
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
        </div>
      </div>

      {/* Summary */}
      {topic.summary && (
        <div style={{ padding: '10px 20px', backgroundColor: '#F9FAFB', fontSize: '13px', color: '#374151', borderBottom: '1px solid #E5E7EB' }}>
          <strong>Summary:</strong> {topic.summary}
        </div>
      )}

      {/* Guidelines */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', marginBottom: '8px' }}>
          Teaching Guidelines
        </div>
        <pre style={{
          fontSize: '13px', lineHeight: '1.6', whiteSpace: 'pre-wrap',
          fontFamily: 'inherit', margin: 0,
        }}>
          {topic.guidelines}
        </pre>
      </div>
    </div>
  </div>
);

/* ─── Main Page ─── */
export default function TopicsAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [topics, setTopics] = useState<ChapterTopicResponseV2[]>([]);
  const [viewingTopic, setViewingTopic] = useState<ChapterTopicResponseV2 | null>(null);
  const [job, setJob] = useState<ProcessingJobResponseV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, topicsData] = await Promise.all([
        getBookV2(bookId),
        getChapterTopics(bookId, chapterId),
      ]);
      setBook(bookData);
      setTopics(topicsData.topics || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [bookId, chapterId]);

  useEffect(() => {
    loadData();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadData]);

  // Resume polling for active extraction jobs
  useEffect(() => {
    if (!bookId || !chapterId) return;
    getLatestJobV2(bookId, chapterId, 'v2_topic_extraction').then(j => {
      if (['pending', 'running'].includes(j.status)) { setJob(j); startPolling(); }
    }).catch(() => {});
    getLatestJobV2(bookId, chapterId, 'v2_refinalization').then(j => {
      if (['pending', 'running'].includes(j.status)) { setJob(j); startPolling(); }
    }).catch(() => {});
  }, [bookId, chapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  const startPolling = useCallback(() => {
    if (!bookId || !chapterId || pollRef.current) return;
    const poll = async () => {
      try {
        // Check both job types
        let active: ProcessingJobResponseV2 | null = null;
        try {
          const j = await getLatestJobV2(bookId!, chapterId!, 'v2_topic_extraction');
          if (['pending', 'running'].includes(j.status)) active = j;
        } catch {}
        if (!active) {
          try {
            const j = await getLatestJobV2(bookId!, chapterId!, 'v2_refinalization');
            if (['pending', 'running'].includes(j.status)) active = j;
          } catch {}
        }

        if (active) {
          setJob(active);
        } else {
          setJob(null);
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          loadData();
        }
      } catch { /* ignore */ }
    };
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL);
  }, [bookId, chapterId, loadData]);

  const handleExtract = async () => {
    if (!bookId || !chapterId) return;
    try {
      const j = await startProcessing(bookId, chapterId);
      setJob(j);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  };

  const handleReprocess = async () => {
    if (!bookId || !chapterId) return;
    if (!confirm('Reprocess will delete existing topics and re-extract. Continue?')) return;
    try {
      const j = await reprocessChapter(bookId, chapterId);
      setJob(j);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  };

  const handleRefinalize = async () => {
    if (!bookId || !chapterId) return;
    try {
      const j = await refinalizeChapter(bookId, chapterId);
      setJob(j);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  };

  const handleView = async (topicKey: string) => {
    if (!bookId || !chapterId) return;
    try {
      const detail = await getTopicDetail(bookId, chapterId, topicKey);
      setViewingTopic(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load topic');
    }
  };

  const handleDelete = async (topicId: string, title: string) => {
    if (!bookId || !chapterId) return;
    if (!confirm(`Delete topic "${title}"?`)) return;
    try {
      await deleteTopic(bookId, chapterId, topicId);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const isRunning = job && ['pending', 'running'].includes(job.status);
  const finalCount = topics.filter(t => ['final', 'approved'].includes(t.status)).length;

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>Extracted Topics</h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.title || chapter?.chapter_title || chapterId}
          &middot; {topics.length} topics ({finalCount} final/approved)
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
        padding: '12px 16px', backgroundColor: '#F9FAFB', borderRadius: '8px', flexWrap: 'wrap',
      }}>
        {topics.length === 0 && (
          <button onClick={handleExtract} disabled={!!isRunning} title="Run topic extraction on OCR text" style={{
            backgroundColor: '#7C3AED', color: 'white', border: 'none', padding: '8px 16px',
            borderRadius: '6px', cursor: isRunning ? 'wait' : 'pointer', fontSize: '13px',
            fontWeight: 600, opacity: isRunning ? 0.6 : 1,
          }}>
            {isRunning ? 'Running...' : 'Extract Topics'}
          </button>
        )}
        {topics.length > 0 && (
          <button onClick={handleReprocess} disabled={!!isRunning} title="Delete all topics and re-extract from OCR text" style={{
            backgroundColor: '#DC2626', color: 'white', border: 'none', padding: '8px 16px',
            borderRadius: '6px', cursor: isRunning ? 'wait' : 'pointer', fontSize: '13px',
            fontWeight: 600, opacity: isRunning ? 0.6 : 1,
          }}>
            Reprocess All
          </button>
        )}
      </div>

      {/* Finalization section — stage 3 (consolidate drafts → finalized topics) */}
      {topics.length > 0 && (() => {
        const draftCount = topics.filter(t => t.status === 'draft').length;
        const consolidatedCount = topics.filter(t => t.status === 'consolidated').length;
        const finalCountLocal = topics.filter(t => t.status === 'final').length;
        const approvedCount = topics.filter(t => t.status === 'approved').length;
        const chapterStatus = chapter?.status || '';
        const statusLabel =
          chapterStatus === 'chapter_completed' ? 'Finalized' :
          chapterStatus === 'needs_review' ? 'Needs Review' :
          chapterStatus === 'topic_extraction' ? 'Extraction running' :
          chapterStatus === 'failed' ? 'Failed' :
          'Not finalized';
        const statusColor =
          chapterStatus === 'chapter_completed' ? '#065F46' :
          chapterStatus === 'needs_review' ? '#92400E' :
          chapterStatus === 'failed' ? '#991B1B' :
          '#6B7280';
        const statusBg =
          chapterStatus === 'chapter_completed' ? '#D1FAE5' :
          chapterStatus === 'needs_review' ? '#FEF3C7' :
          chapterStatus === 'failed' ? '#FEE2E2' :
          '#F3F4F6';
        return (
          <div style={{
            marginBottom: '20px', padding: '14px 16px',
            border: '1px solid #E5E7EB', borderRadius: '8px', backgroundColor: 'white',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
              <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#111827' }}>Finalization</h3>
              <span style={{
                fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
                backgroundColor: statusBg, color: statusColor,
              }}>{statusLabel}</span>
            </div>

            <div style={{ fontSize: '12px', color: '#374151', marginBottom: '12px' }}>
              {topics.length} topics total · draft: {draftCount} · consolidated: {consolidatedCount} · final: {finalCountLocal} · approved: {approvedCount}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button onClick={handleRefinalize} disabled={!!isRunning} title="Re-run finalization: consolidate, dedupe, reorder draft topics" style={{
                backgroundColor: '#6366F1', color: 'white', border: 'none', padding: '7px 14px',
                borderRadius: '5px', cursor: isRunning ? 'wait' : 'pointer', fontSize: '12px',
                fontWeight: 600, opacity: isRunning ? 0.6 : 1,
              }}>
                {isRunning && job?.job_type === 'v2_refinalization' ? 'Finalizing...' : 'Re-finalize'}
              </button>
            </div>

            {isRunning && job?.job_type === 'v2_refinalization' && (
              <div style={{
                marginTop: '10px', padding: '8px 12px', backgroundColor: '#EEF2FF', borderRadius: '6px',
                fontSize: '12px', color: '#3730A3',
              }}>
                {job.current_item ? `Finalizing: ${job.current_item}` : 'Running finalization...'}
                {job.completed_items !== undefined && job.total_items !== undefined && (
                  <> · {job.completed_items}/{job.total_items}</>
                )}
              </div>
            )}
          </div>
        );
      })()}

      {/* Job progress */}
      {isRunning && job && (
        <div style={{
          padding: '10px 16px', backgroundColor: '#EDE9FE', borderRadius: '8px', marginBottom: '16px',
          display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px',
        }}>
          <span style={{ fontWeight: 600, color: '#5B21B6' }}>
            {job.current_item ? `Processing: ${job.current_item}` : 'Starting...'}
          </span>
          {job.total_items && (
            <span style={{ color: '#7C3AED' }}>
              {job.completed_items}/{job.total_items}
              {job.failed_items > 0 && ` (${job.failed_items} failed)`}
            </span>
          )}
        </div>
      )}

      {/* Topic list */}
      <div style={{ border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 1fr 90px 60px 180px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>#</span>
          <span>Topic</span>
          <span>Status</span>
          <span>Pages</span>
          <span>Actions</span>
        </div>

        {topics.map((t, i) => (
          <div key={t.id} style={{
            display: 'grid', gridTemplateColumns: '40px 1fr 90px 60px 180px',
            padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
            backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
          }}>
            <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{t.sequence_order ?? i + 1}</span>
            <div>
              <span style={{ fontSize: '13px', fontWeight: 500 }}>{t.topic_title}</span>
              {t.summary && (
                <div style={{ fontSize: '11px', color: '#9CA3AF', marginTop: '2px', lineHeight: '1.3' }}>
                  {t.summary.length > 80 ? t.summary.slice(0, 80) + '...' : t.summary}
                </div>
              )}
            </div>
            <StatusBadge status={t.status} />
            <span style={{ fontSize: '12px', color: '#6B7280' }}>
              {t.source_page_start ? `${t.source_page_start}–${t.source_page_end || '?'}` : '–'}
            </span>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button onClick={() => handleView(t.topic_key)} style={actionBtn('#2563EB', false)}>
                View
              </button>
              <button onClick={() => handleDelete(t.id, t.topic_title)} style={actionBtn('#DC2626', false)}>
                Delete
              </button>
            </div>
          </div>
        ))}

        {topics.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            No topics extracted yet. {chapter?.status === 'upload_complete' ? 'Click "Extract Topics" to start.' : ''}
          </div>
        )}
      </div>

      {/* Topic Detail Modal */}
      {viewingTopic && (
        <TopicModal topic={viewingTopic} onClose={() => setViewingTopic(null)} />
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
