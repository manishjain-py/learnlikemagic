import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, getGuidelineStatus, getGuidelineDetail, updateGuideline, deleteGuideline, syncChapter,
  BookV2DetailResponse, GuidelineStatusItemV2, GuidelineDetailResponseV2,
} from '../api/adminApiV2';

/* ─── Status Badge ─── */
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    APPROVED: { bg: '#D1FAE5', color: '#065F46', label: 'Approved' },
    TO_BE_REVIEWED: { bg: '#FEF3C7', color: '#92400E', label: 'To Review' },
    REJECTED: { bg: '#FEE2E2', color: '#991B1B', label: 'Rejected' },
  };
  const c = cfg[status] || { bg: '#F3F4F6', color: '#6B7280', label: status };
  return (
    <span style={{
      fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
      backgroundColor: c.bg, color: c.color,
    }}>{c.label}</span>
  );
};

/* ─── Guideline Viewer/Editor Modal ─── */
const GuidelineModal: React.FC<{
  detail: GuidelineDetailResponseV2;
  bookId: string;
  onClose: () => void;
  onSaved: () => void;
}> = ({ detail, bookId, onClose, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(detail.guideline);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateGuideline(bookId, detail.id, { guideline: text });
      setEditing(false);
      onSaved();
    } catch { /* ignore */ }
    setSaving(false);
  };

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
            <div style={{ fontWeight: 700, fontSize: '16px' }}>{detail.topic_title}</div>
            <div style={{ fontSize: '12px', color: '#6B7280', marginTop: '2px' }}>
              {detail.topic_key}
              {detail.source_page_start && ` · Pages ${detail.source_page_start}–${detail.source_page_end || '?'}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <StatusBadge status={detail.review_status} />
            <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
          </div>
        </div>

        {/* Summary */}
        {detail.topic_summary && (
          <div style={{ padding: '10px 20px', backgroundColor: '#F9FAFB', fontSize: '13px', color: '#374151', borderBottom: '1px solid #E5E7EB' }}>
            <strong>Summary:</strong> {detail.topic_summary}
          </div>
        )}

        {/* Content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          {editing ? (
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              style={{
                width: '100%', minHeight: '400px', padding: '12px',
                border: '1px solid #D1D5DB', borderRadius: '6px',
                fontSize: '13px', lineHeight: '1.6', fontFamily: 'inherit', resize: 'vertical',
              }}
            />
          ) : (
            <pre style={{
              fontSize: '13px', lineHeight: '1.6', whiteSpace: 'pre-wrap',
              fontFamily: 'inherit', margin: 0,
            }}>
              {detail.guideline}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 20px', borderTop: '1px solid #E5E7EB',
          display: 'flex', gap: '8px', justifyContent: 'flex-end',
        }}>
          {editing ? (
            <>
              <button onClick={() => { setEditing(false); setText(detail.guideline); }}
                style={{ padding: '8px 16px', border: '1px solid #D1D5DB', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', backgroundColor: 'white' }}>
                Cancel
              </button>
              <button onClick={handleSave} disabled={saving}
                style={{ padding: '8px 16px', backgroundColor: '#10B981', color: 'white', border: 'none', borderRadius: '6px', cursor: saving ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <button onClick={() => setEditing(true)}
              style={{ padding: '8px 16px', backgroundColor: '#3B82F6', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
              Edit
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

/* ─── Main Page ─── */
export default function GuidelinesAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [guidelines, setGuidelines] = useState<GuidelineStatusItemV2[]>([]);
  const [viewingDetail, setViewingDetail] = useState<GuidelineDetailResponseV2 | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, glStatus] = await Promise.all([
        getBookV2(bookId),
        getGuidelineStatus(bookId, chapterId),
      ]);
      setBook(bookData);
      setGuidelines(glStatus.guidelines || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [bookId, chapterId]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleView = async (guidelineId: string) => {
    if (!bookId) return;
    try {
      const detail = await getGuidelineDetail(bookId, guidelineId);
      setViewingDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load guideline');
    }
  };

  const handleApprove = async (guidelineId: string, currentStatus: string) => {
    if (!bookId) return;
    const newStatus = currentStatus === 'APPROVED' ? 'TO_BE_REVIEWED' : 'APPROVED';
    try {
      await updateGuideline(bookId, guidelineId, { review_status: newStatus });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleSync = async () => {
    if (!bookId || !chapterId) return;
    setSyncing(true);
    try {
      await syncChapter(bookId, chapterId);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync failed');
    }
    setSyncing(false);
  };

  const handleDelete = async (guidelineId: string, title: string) => {
    if (!bookId) return;
    if (!confirm(`Delete guideline "${title}" and its explanations? This cannot be undone.`)) return;
    try {
      await deleteGuideline(bookId, guidelineId);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleApproveAll = async () => {
    if (!bookId) return;
    const unapproved = guidelines.filter(g => g.review_status !== 'APPROVED');
    if (!unapproved.length) return;
    if (!confirm(`Approve all ${unapproved.length} unapproved guidelines?`)) return;
    try {
      await Promise.all(unapproved.map(g => updateGuideline(bookId, g.guideline_id, { review_status: 'APPROVED' })));
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve all');
    }
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const approvedCount = guidelines.filter(g => g.review_status === 'APPROVED').length;

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>Teaching Guidelines</h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.title || chapter?.chapter_title || chapterId}
          &middot; {approvedCount}/{guidelines.length} approved
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
        <button onClick={handleSync} disabled={syncing} style={{
          backgroundColor: '#10B981', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: syncing ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: syncing ? 0.6 : 1,
        }}>
          {syncing ? 'Syncing...' : 'Re-sync from V2 Topics'}
        </button>
        <button onClick={handleApproveAll} style={{
          backgroundColor: '#065F46', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
        }}>
          Approve All
        </button>
      </div>

      {/* Guideline list */}
      <div style={{ border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 1fr 90px 60px 200px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>#</span>
          <span>Topic</span>
          <span>Status</span>
          <span>Pages</span>
          <span>Actions</span>
        </div>

        {guidelines.map((g, i) => (
          <div key={g.guideline_id} style={{
            display: 'grid', gridTemplateColumns: '40px 1fr 90px 60px 200px',
            padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
            backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
          }}>
            <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{i + 1}</span>
            <div>
              <span style={{ fontSize: '13px', fontWeight: 500 }}>{g.topic_title}</span>
              {g.has_explanations && (
                <span style={{ fontSize: '10px', color: '#6B7280', marginLeft: '8px' }}>has explanations</span>
              )}
            </div>
            <StatusBadge status={g.review_status} />
            <span style={{ fontSize: '12px', color: '#6B7280' }}>
              {g.source_page_start ? `${g.source_page_start}–${g.source_page_end || '?'}` : '–'}
            </span>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button onClick={() => handleView(g.guideline_id)} style={actionBtn('#2563EB', false)}>
                View
              </button>
              <button onClick={() => handleApprove(g.guideline_id, g.review_status)}
                style={actionBtn(g.review_status === 'APPROVED' ? '#F59E0B' : '#10B981', false)}>
                {g.review_status === 'APPROVED' ? 'Unapprove' : 'Approve'}
              </button>
              <button onClick={() => handleDelete(g.guideline_id, g.topic_title)}
                style={actionBtn('#DC2626', false)}>
                Delete
              </button>
            </div>
          </div>
        ))}

        {guidelines.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            No guidelines in this chapter. Try syncing from V2 topics.
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {viewingDetail && bookId && (
        <GuidelineModal
          detail={viewingDetail}
          bookId={bookId}
          onClose={() => setViewingDetail(null)}
          onSaved={() => { setViewingDetail(null); loadData(); }}
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
