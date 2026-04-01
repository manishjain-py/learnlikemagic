import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, getChapterPages, getPageDetailV2, retryPageOcrV2,
  bulkOcrRetry, bulkOcrRerun, getLatestJobV2,
  BookV2DetailResponse, PageResponseV2, PageDetailResponseV2, ProcessingJobResponseV2,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

/* ─── Status Badge ─── */
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    pending: { bg: '#F3F4F6', color: '#6B7280', label: 'Pending' },
    processing: { bg: '#EDE9FE', color: '#5B21B6', label: 'Processing' },
    completed: { bg: '#D1FAE5', color: '#065F46', label: 'Completed' },
    failed: { bg: '#FEE2E2', color: '#991B1B', label: 'Failed' },
  };
  const c = cfg[status] || cfg.pending;
  return (
    <span style={{
      fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
      backgroundColor: c.bg, color: c.color,
    }}>{c.label}</span>
  );
};

/* ─── Page Detail Modal ─── */
const PageDetailModal: React.FC<{
  detail: PageDetailResponseV2;
  onClose: () => void;
}> = ({ detail, onClose }) => (
  <div style={{
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
    display: 'flex', justifyContent: 'center', alignItems: 'center',
  }} onClick={onClose}>
    <div style={{
      backgroundColor: 'white', borderRadius: '12px', width: '95%', maxWidth: '1200px',
      maxHeight: '90vh', display: 'flex', flexDirection: 'column',
    }} onClick={e => e.stopPropagation()}>
      {/* Header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: '16px' }}>Page {detail.page_number}</div>
          <div style={{ fontSize: '12px', color: '#6B7280' }}>
            <StatusBadge status={detail.ocr_status} />
            {detail.ocr_error && <span style={{ color: '#DC2626', marginLeft: '8px' }}>{detail.ocr_error}</span>}
          </div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
      </div>

      {/* Side-by-side content */}
      <div style={{ flex: 1, overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0' }}>
        {/* Image */}
        <div style={{ padding: '16px', borderRight: '1px solid #E5E7EB', overflow: 'auto' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', marginBottom: '8px' }}>
            Original Image
          </div>
          {detail.image_url ? (
            <img src={detail.image_url} alt={`Page ${detail.page_number}`} style={{ width: '100%', borderRadius: '4px' }} />
          ) : (
            <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>No image available</div>
          )}
        </div>
        {/* OCR Text */}
        <div style={{ padding: '16px', overflow: 'auto' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', marginBottom: '8px' }}>
            OCR Text
          </div>
          {detail.ocr_text ? (
            <pre style={{
              fontSize: '13px', lineHeight: '1.6', whiteSpace: 'pre-wrap',
              fontFamily: 'inherit', margin: 0,
            }}>
              {detail.ocr_text}
            </pre>
          ) : (
            <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>
              {detail.ocr_status === 'failed' ? 'OCR failed' : 'No OCR text yet'}
            </div>
          )}
        </div>
      </div>
    </div>
  </div>
);

/* ─── Main Page ─── */
export default function OCRAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [pages, setPages] = useState<PageResponseV2[]>([]);
  const [ocrJob, setOcrJob] = useState<ProcessingJobResponseV2 | null>(null);
  const [viewingDetail, setViewingDetail] = useState<PageDetailResponseV2 | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, pagesData] = await Promise.all([
        getBookV2(bookId),
        getChapterPages(bookId, chapterId),
      ]);
      setBook(bookData);
      setPages(pagesData.pages || []);
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

  // Check for active OCR jobs on mount
  useEffect(() => {
    if (!bookId || !chapterId) return;
    getLatestJobV2(bookId, chapterId, 'v2_ocr').then(job => {
      if (['pending', 'running'].includes(job.status)) {
        setOcrJob(job);
        startPolling();
      }
    }).catch(() => {});
  }, [bookId, chapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  const startPolling = useCallback(() => {
    if (!bookId || !chapterId || pollRef.current) return;
    const poll = async () => {
      try {
        const job = await getLatestJobV2(bookId!, chapterId!, 'v2_ocr');
        setOcrJob(job);
        if (['completed', 'failed', 'completed_with_errors'].includes(job.status)) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          loadData();
        }
      } catch { /* ignore */ }
    };
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL);
  }, [bookId, chapterId, loadData]);

  const handleRetry = async (pageNum: number) => {
    if (!bookId || !chapterId) return;
    try {
      await retryPageOcrV2(bookId, chapterId, pageNum);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retry failed');
    }
  };

  const handleBulkRetry = async () => {
    if (!bookId || !chapterId) return;
    try {
      const job = await bulkOcrRetry(bookId, chapterId);
      setOcrJob(job);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk retry failed');
    }
  };

  const handleBulkRerun = async () => {
    if (!bookId || !chapterId) return;
    if (!confirm('Rerun OCR on all pages? This will overwrite existing OCR text.')) return;
    try {
      const job = await bulkOcrRerun(bookId, chapterId);
      setOcrJob(job);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk rerun failed');
    }
  };

  const handleViewDetail = async (pageNum: number) => {
    if (!bookId || !chapterId) return;
    setDetailLoading(true);
    try {
      const detail = await getPageDetailV2(bookId, chapterId, pageNum);
      setViewingDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load page');
    }
    setDetailLoading(false);
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const isRunning = ocrJob && ['pending', 'running'].includes(ocrJob.status);
  const completedCount = pages.filter(p => p.ocr_status === 'completed').length;
  const failedCount = pages.filter(p => p.ocr_status === 'failed').length;

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>OCR Results</h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.title || chapter?.chapter_title || chapterId}
          &middot; {completedCount}/{pages.length} completed
          {failedCount > 0 && <span style={{ color: '#DC2626' }}> ({failedCount} failed)</span>}
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
        <button onClick={handleBulkRetry} disabled={!!isRunning} title="Retry OCR on all failed pages" style={{
          backgroundColor: '#F59E0B', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isRunning ? 0.6 : 1,
        }}>
          {isRunning ? 'Running...' : 'Retry Failed'}
        </button>
        <button onClick={handleBulkRerun} disabled={!!isRunning} title="Force rerun OCR on all pages (overwrites existing)" style={{
          backgroundColor: '#DC2626', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isRunning ? 0.6 : 1,
        }}>
          Rerun All
        </button>
      </div>

      {/* Job progress */}
      {isRunning && ocrJob && (
        <div style={{
          padding: '10px 16px', backgroundColor: '#EDE9FE', borderRadius: '8px', marginBottom: '16px',
          display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px',
        }}>
          <span style={{ fontWeight: 600, color: '#5B21B6' }}>
            {ocrJob.current_item ? `Processing: ${ocrJob.current_item}` : 'Starting...'}
          </span>
          {ocrJob.total_items && (
            <span style={{ color: '#7C3AED' }}>
              {ocrJob.completed_items}/{ocrJob.total_items}
              {ocrJob.failed_items > 0 && ` (${ocrJob.failed_items} failed)`}
            </span>
          )}
        </div>
      )}

      {/* Page list */}
      <div style={{ border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '60px 1fr 100px 180px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>Page</span>
          <span>Details</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {pages.map((p, i) => (
          <div key={p.id} style={{
            display: 'grid', gridTemplateColumns: '60px 1fr 100px 180px',
            padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
            backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
          }}>
            <span style={{ fontSize: '13px', fontWeight: 600 }}>{p.page_number}</span>
            <div style={{ fontSize: '12px', color: '#6B7280' }}>
              {p.ocr_error && <span style={{ color: '#DC2626' }}>{p.ocr_error}</span>}
              {p.ocr_completed_at && !p.ocr_error && (
                <span>Completed {new Date(p.ocr_completed_at).toLocaleDateString()}</span>
              )}
            </div>
            <StatusBadge status={p.ocr_status} />
            <div style={{ display: 'flex', gap: '6px' }}>
              <button onClick={() => handleViewDetail(p.page_number)} disabled={detailLoading} style={actionBtn('#2563EB', false)}>
                View
              </button>
              {p.ocr_status === 'failed' && (
                <button onClick={() => handleRetry(p.page_number)} style={actionBtn('#F59E0B', false)}>
                  Retry
                </button>
              )}
            </div>
          </div>
        ))}

        {pages.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            No pages uploaded for this chapter
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {viewingDetail && (
        <PageDetailModal detail={viewingDetail} onClose={() => setViewingDetail(null)} />
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
