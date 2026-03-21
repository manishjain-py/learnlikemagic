import React, { useState, useEffect } from 'react';
import { listIssues, updateIssueStatus, getScreenshotUrl, type IssueResponse } from '../../../api';

const STATUS_OPTIONS = ['all', 'open', 'in_progress', 'closed'] as const;
const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: '#FEF3C7', text: '#92400E' },
  in_progress: { bg: '#DBEAFE', text: '#1E40AF' },
  closed: { bg: '#D1FAE5', text: '#065F46' },
};
const STATUS_LABELS: Record<string, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  closed: 'Closed',
};

export default function AdminIssuesPage() {
  const [issues, setIssues] = useState<IssueResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [selectedIssue, setSelectedIssue] = useState<IssueResponse | null>(null);
  const [screenshotUrls, setScreenshotUrls] = useState<Record<string, string>>({});

  const fetchIssues = async () => {
    setLoading(true);
    try {
      const statusParam = filter === 'all' ? undefined : filter;
      const data = await listIssues(statusParam);
      setIssues(data.issues);
      setTotal(data.total);
    } catch (e) {
      console.error('Failed to load issues', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchIssues(); }, [filter]);

  const handleStatusChange = async (issueId: string, newStatus: string) => {
    try {
      const updated = await updateIssueStatus(issueId, newStatus);
      setIssues((prev) => prev.map((i) => (i.id === issueId ? updated : i)));
      if (selectedIssue?.id === issueId) setSelectedIssue(updated);
    } catch (e) {
      console.error('Failed to update status', e);
    }
  };

  const openDetail = async (issue: IssueResponse) => {
    setSelectedIssue(issue);
    // Load screenshot URLs
    if (issue.screenshot_s3_keys?.length) {
      const urls: Record<string, string> = {};
      for (const key of issue.screenshot_s3_keys) {
        try {
          urls[key] = await getScreenshotUrl(issue.id, key);
        } catch { /* ignore */ }
      }
      setScreenshotUrls(urls);
    } else {
      setScreenshotUrls({});
    }
  };

  const formatDate = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) +
      ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  };

  // ── Detail view ─────────────────────────────────
  if (selectedIssue) {
    return (
      <div style={{ padding: '32px 24px', maxWidth: '800px', margin: '0 auto' }}>
        <button
          onClick={() => setSelectedIssue(null)}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            border: 'none', background: 'none', color: '#4F46E5',
            cursor: 'pointer', fontSize: '14px', fontWeight: 500, padding: 0,
            marginBottom: '20px',
          }}
        >
          &larr; Back to Issues
        </button>

        <div style={{
          backgroundColor: 'white', borderRadius: '12px',
          border: '1px solid #E5E7EB', padding: '24px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
            <h2 style={{ margin: 0, fontSize: '20px', color: '#111827', flex: 1 }}>
              {selectedIssue.title}
            </h2>
            <select
              value={selectedIssue.status}
              onChange={(e) => handleStatusChange(selectedIssue.id, e.target.value)}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid #D1D5DB',
                fontSize: '13px',
                fontWeight: 500,
                backgroundColor: STATUS_COLORS[selectedIssue.status]?.bg || '#F3F4F6',
                color: STATUS_COLORS[selectedIssue.status]?.text || '#374151',
                cursor: 'pointer',
                marginLeft: '16px',
              }}
            >
              <option value="open">Open</option>
              <option value="in_progress">In Progress</option>
              <option value="closed">Closed</option>
            </select>
          </div>

          <div style={{ fontSize: '13px', color: '#9CA3AF', marginBottom: '16px' }}>
            Reported by {selectedIssue.reporter_name || 'Unknown'} on {formatDate(selectedIssue.created_at)}
          </div>

          <div style={{ marginBottom: '20px' }}>
            <h4 style={{ margin: '0 0 8px', color: '#374151', fontSize: '14px' }}>Description</h4>
            <p style={{ margin: 0, color: '#374151', fontSize: '14px', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
              {selectedIssue.description}
            </p>
          </div>

          {selectedIssue.original_input && (
            <div style={{ marginBottom: '20px' }}>
              <h4 style={{ margin: '0 0 8px', color: '#374151', fontSize: '14px' }}>Original Input</h4>
              <div style={{
                backgroundColor: '#F9FAFB', borderRadius: '8px', padding: '12px',
                fontSize: '13px', color: '#6B7280', whiteSpace: 'pre-wrap',
              }}>
                {selectedIssue.original_input}
              </div>
            </div>
          )}

          {selectedIssue.screenshot_s3_keys && selectedIssue.screenshot_s3_keys.length > 0 && (
            <div>
              <h4 style={{ margin: '0 0 8px', color: '#374151', fontSize: '14px' }}>
                Screenshots ({selectedIssue.screenshot_s3_keys.length})
              </h4>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                {selectedIssue.screenshot_s3_keys.map((key) => (
                  <a
                    key={key}
                    href={screenshotUrls[key] || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'block',
                      width: '160px',
                      height: '120px',
                      borderRadius: '8px',
                      border: '1px solid #E5E7EB',
                      overflow: 'hidden',
                      backgroundColor: '#F3F4F6',
                    }}
                  >
                    {screenshotUrls[key] ? (
                      <img
                        src={screenshotUrls[key]}
                        alt="Screenshot"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                    ) : (
                      <div style={{
                        width: '100%', height: '100%',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: '#9CA3AF', fontSize: '12px',
                      }}>
                        Loading...
                      </div>
                    )}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── List view ───────────────────────────────────
  return (
    <div style={{ padding: '32px 24px', maxWidth: '1000px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, margin: 0, color: '#111827' }}>Issues</h1>
          <p style={{ color: '#6B7280', marginTop: '4px', fontSize: '14px' }}>{total} total</p>
        </div>

        <div style={{ display: 'flex', gap: '4px' }}>
          {STATUS_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              style={{
                padding: '6px 14px',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: filter === s ? '#EEF2FF' : 'transparent',
                color: filter === s ? '#4F46E5' : '#6B7280',
                fontWeight: filter === s ? 600 : 500,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              {s === 'all' ? 'All' : STATUS_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p style={{ textAlign: 'center', color: '#9CA3AF', padding: '40px 0' }}>Loading...</p>
      ) : issues.length === 0 ? (
        <p style={{ textAlign: 'center', color: '#9CA3AF', padding: '40px 0' }}>No issues found.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {issues.map((issue) => (
            <button
              key={issue.id}
              onClick={() => openDetail(issue)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '16px',
                padding: '16px 20px',
                backgroundColor: 'white',
                border: '1px solid #E5E7EB',
                borderRadius: '10px',
                cursor: 'pointer',
                textAlign: 'left',
                width: '100%',
                transition: 'box-shadow 0.15s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'none'; }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '15px', fontWeight: 600, color: '#111827', marginBottom: '4px' }}>
                  {issue.title}
                </div>
                <div style={{ fontSize: '13px', color: '#9CA3AF' }}>
                  {issue.reporter_name || 'Unknown'} &middot; {formatDate(issue.created_at)}
                </div>
              </div>

              <span style={{
                padding: '4px 10px',
                borderRadius: '12px',
                fontSize: '12px',
                fontWeight: 600,
                backgroundColor: STATUS_COLORS[issue.status]?.bg || '#F3F4F6',
                color: STATUS_COLORS[issue.status]?.text || '#374151',
                whiteSpace: 'nowrap',
              }}>
                {STATUS_LABELS[issue.status] || issue.status}
              </span>

              <select
                value={issue.status}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => { e.stopPropagation(); handleStatusChange(issue.id, e.target.value); }}
                style={{
                  padding: '4px 8px',
                  borderRadius: '6px',
                  border: '1px solid #E5E7EB',
                  fontSize: '12px',
                  cursor: 'pointer',
                  color: '#6B7280',
                  backgroundColor: 'white',
                }}
              >
                <option value="open">Open</option>
                <option value="in_progress">In Progress</option>
                <option value="closed">Closed</option>
              </select>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
