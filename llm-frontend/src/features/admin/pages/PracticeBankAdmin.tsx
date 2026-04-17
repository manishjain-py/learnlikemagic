import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, generatePracticeBanks, getPracticeBankJobStatus,
  getPracticeBankStatus, getPracticeBank,
  BookV2DetailResponse, ProcessingJobResponseV2,
  TopicPracticeBankStatusV2, PracticeBankDetailResponseV2, PracticeBankQuestionItemV2,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

/* ─── Format badge ─── */
const FORMAT_COLOR: Record<string, { bg: string; color: string }> = {
  pick_one:            { bg: '#EDE9FE', color: '#5B21B6' },
  true_false:          { bg: '#DBEAFE', color: '#1D4ED8' },
  fill_blank:          { bg: '#FEF3C7', color: '#92400E' },
  match_pairs:         { bg: '#D1FAE5', color: '#065F46' },
  sort_buckets:        { bg: '#CCFBF1', color: '#115E59' },
  sequence:            { bg: '#FCE7F3', color: '#9D174D' },
  spot_the_error:      { bg: '#FEE2E2', color: '#991B1B' },
  odd_one_out:         { bg: '#E0E7FF', color: '#3730A3' },
  predict_then_reveal: { bg: '#FFE4E6', color: '#9F1239' },
  swipe_classify:      { bg: '#F0FDF4', color: '#166534' },
  tap_to_eliminate:    { bg: '#FEF9C3', color: '#854D0E' },
  free_form:           { bg: '#F3F4F6', color: '#374151' },
};

const DIFF_COLOR: Record<string, string> = {
  easy: '#10B981', medium: '#F59E0B', hard: '#EF4444',
};

/* ─── Correct-answer summary per format ─── */
function summarizeCorrectAnswer(fmt: string, q: Record<string, unknown>): string {
  switch (fmt) {
    case 'pick_one':
    case 'fill_blank':
    case 'tap_to_eliminate':
    case 'predict_then_reveal': {
      const opts = q.options as string[] | undefined;
      const idx = q.correct_index as number | undefined;
      return opts && idx !== undefined ? `[${idx}] ${opts[idx]}` : '—';
    }
    case 'true_false':
      return q.correct_answer_bool ? 'TRUE' : 'FALSE';
    case 'match_pairs': {
      const pairs = q.pairs as Array<{ left: string; right: string }> | undefined;
      return pairs?.map(p => `${p.left} ↔ ${p.right}`).join(', ') || '—';
    }
    case 'sort_buckets':
    case 'swipe_classify': {
      const names = q.bucket_names as string[] | undefined;
      const items = q.bucket_items as Array<{ text: string; correct_bucket: number }> | undefined;
      if (!names || !items) return '—';
      return items.map(bi => `${bi.text} → ${names[bi.correct_bucket]}`).join(', ');
    }
    case 'sequence':
      return (q.sequence_items as string[] | undefined)?.join(' → ') || '—';
    case 'spot_the_error': {
      const steps = q.error_steps as string[] | undefined;
      const idx = q.error_index as number | undefined;
      return steps && idx !== undefined ? `Step ${idx}: ${steps[idx]}` : '—';
    }
    case 'odd_one_out': {
      const items = q.odd_items as string[] | undefined;
      const idx = q.odd_index as number | undefined;
      return items && idx !== undefined ? `[${idx}] ${items[idx]}` : '—';
    }
    case 'free_form':
      return (q.expected_answer as string | undefined) || '—';
    default:
      return '—';
  }
}

/* ─── Question row — collapsed + expanded ─── */
const QuestionRow: React.FC<{ q: PracticeBankQuestionItemV2; idx: number }> = ({ q, idx }) => {
  const [open, setOpen] = useState(false);
  const qj = q.question_json;
  const text = (qj.question_text as string) || '';
  const fmtStyle = FORMAT_COLOR[q.format] || { bg: '#F3F4F6', color: '#374151' };
  const diffColor = DIFF_COLOR[q.difficulty] || '#6B7280';

  return (
    <div style={{
      borderTop: '1px solid #E5E7EB',
      backgroundColor: idx % 2 === 0 ? 'white' : '#FAFAFA',
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'grid',
          gridTemplateColumns: '32px 140px 72px 160px 1fr 24px',
          padding: '10px 16px', alignItems: 'center', gap: '12px',
          cursor: 'pointer', fontSize: '13px',
        }}
      >
        <span style={{ color: '#9CA3AF', fontSize: '11px' }}>{idx + 1}</span>
        <span style={{
          fontSize: '10px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
          backgroundColor: fmtStyle.bg, color: fmtStyle.color, textAlign: 'center',
        }}>
          {q.format}
        </span>
        <span style={{
          fontSize: '10px', fontWeight: 600, color: diffColor, textTransform: 'uppercase',
        }}>
          {q.difficulty}
        </span>
        <span style={{ fontSize: '11px', color: '#6B7280', fontFamily: 'monospace' }}>
          {q.concept_tag}
        </span>
        <span style={{
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: '#374151',
        }}>
          {text}
        </span>
        <span style={{ color: '#9CA3AF', fontSize: '11px' }}>{open ? '▾' : '▸'}</span>
      </div>

      {open && (
        <div style={{
          padding: '12px 16px 16px 60px', borderTop: '1px dashed #E5E7EB',
          fontSize: '12px', color: '#374151', lineHeight: '1.55',
        }}>
          <div style={{ marginBottom: '8px' }}>
            <span style={{ fontWeight: 600 }}>Question: </span>
            <span style={{ whiteSpace: 'pre-wrap' }}>{text}</span>
          </div>
          <div style={{ marginBottom: '8px' }}>
            <span style={{ fontWeight: 600 }}>Correct: </span>
            <span style={{ whiteSpace: 'pre-wrap' }}>{summarizeCorrectAnswer(q.format, qj)}</span>
          </div>
          {qj.explanation_why && (
            <div style={{ marginBottom: '8px' }}>
              <span style={{ fontWeight: 600 }}>Why: </span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{qj.explanation_why as string}</span>
            </div>
          )}
          {q.format === 'free_form' && qj.grading_rubric && (
            <div style={{ marginBottom: '8px' }}>
              <span style={{ fontWeight: 600 }}>Rubric: </span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{qj.grading_rubric as string}</span>
            </div>
          )}
          <details style={{ marginTop: '10px' }}>
            <summary style={{ cursor: 'pointer', color: '#6B7280', fontSize: '11px' }}>Raw JSON</summary>
            <pre style={{
              marginTop: '6px', padding: '10px', backgroundColor: '#F9FAFB',
              border: '1px solid #E5E7EB', borderRadius: '4px', fontSize: '11px',
              overflow: 'auto', fontFamily: 'monospace',
            }}>
              {JSON.stringify(qj, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
};

/* ─── Main page ─── */
export default function PracticeBankAdmin() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [topics, setTopics] = useState<TopicPracticeBankStatusV2[]>([]);
  const [chapterJob, setChapterJob] = useState<ProcessingJobResponseV2 | null>(null);
  const [topicJobs, setTopicJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [viewing, setViewing] = useState<PracticeBankDetailResponseV2 | null>(null);
  const [reviewRounds, setReviewRounds] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chapterPollRef = useRef<NodeJS.Timeout | null>(null);
  const topicPollRef = useRef<Record<string, NodeJS.Timeout>>({});

  const chapter = book?.chapters?.find(ch => ch.id === chapterId);

  const loadData = useCallback(async () => {
    if (!bookId || !chapterId) return;
    try {
      const [bookData, statusResp] = await Promise.all([
        getBookV2(bookId),
        getPracticeBankStatus(bookId, chapterId),
      ]);
      setBook(bookData);
      setTopics(statusResp.topics || []);
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

  // Resume polling on mount if jobs are still active
  useEffect(() => {
    if (!bookId || !chapterId || !topics.length) return;
    getPracticeBankJobStatus(bookId, { chapterId }).then(job => {
      if (['pending', 'running'].includes(job.status)) {
        setChapterJob(job);
        startChapterPolling();
      }
    }).catch(() => {});
    topics.forEach(t => {
      getPracticeBankJobStatus(bookId, { guidelineId: t.guideline_id }).then(job => {
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
        const job = await getPracticeBankJobStatus(bookId!, { chapterId });
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
        const job = await getPracticeBankJobStatus(bookId!, { guidelineId });
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
      const job = await generatePracticeBanks(bookId, {
        chapterId: guidelineId ? undefined : chapterId,
        guidelineId,
        force,
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

  const handleView = async (guidelineId: string) => {
    if (!bookId) return;
    try {
      const detail = await getPracticeBank(bookId, guidelineId);
      setViewing(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load bank');
    }
  };

  const getTopicStatus = (guidelineId: string, questionCount: number): string => {
    const topicJob = topicJobs[guidelineId];
    const chapterRunning = chapterJob && ['pending', 'running'].includes(chapterJob.status);
    if (topicJob && ['pending', 'running'].includes(topicJob.status)) return 'running';
    if (chapterRunning) return 'running';
    if (questionCount > 0) return 'success';
    if (topicJob && topicJob.status === 'failed') return 'failed';
    return 'not_generated';
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>Loading...</div>;

  const isChapterRunning = chapterJob && ['pending', 'running'].includes(chapterJob.status);

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      <div style={{ marginBottom: '24px' }}>
        <button onClick={() => navigate(`/admin/books-v2/${bookId}`)} style={{
          background: 'none', border: 'none', color: '#6B7280', cursor: 'pointer', fontSize: '13px', marginBottom: '8px',
        }}>&larr; Back to Book</button>
        <h1 style={{ margin: 0, fontSize: '22px' }}>Practice Banks</h1>
        <div style={{ fontSize: '14px', color: '#6B7280', marginTop: '4px' }}>
          {book?.title} &middot; {chapter?.chapter_title || chapterId}
        </div>
      </div>

      {error && (
        <div style={{ backgroundColor: '#FEE2E2', color: '#991B1B', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
          <button onClick={() => setError(null)} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px',
        padding: '12px 16px', backgroundColor: '#F9FAFB', borderRadius: '8px',
      }}>
        <button onClick={() => handleGenerate()} disabled={!!isChapterRunning} title="Generate banks for topics that don't have one yet (skips existing)" style={{
          backgroundColor: '#0891B2', color: 'white', border: 'none', padding: '8px 16px',
          borderRadius: '6px', cursor: isChapterRunning ? 'wait' : 'pointer', fontSize: '13px',
          fontWeight: 600, opacity: isChapterRunning ? 0.6 : 1,
        }}>
          {isChapterRunning ? 'Running...' : 'Generate All'}
        </button>
        <button onClick={() => handleGenerate(undefined, true)} disabled={!!isChapterRunning} title="Delete all existing banks in this chapter and regenerate from scratch" style={{
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

      {isChapterRunning && chapterJob && (
        <div style={{
          padding: '10px 16px', backgroundColor: '#CCFBF1', borderRadius: '8px', marginBottom: '16px',
          display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px',
        }}>
          <span style={{ fontWeight: 600, color: '#115E59' }}>
            {chapterJob.current_item ? `Processing: ${chapterJob.current_item}` : 'Starting...'}
          </span>
          {chapterJob.total_items && (
            <span style={{ color: '#0891B2' }}>
              {chapterJob.completed_items}/{chapterJob.total_items}
              {chapterJob.failed_items > 0 && ` (${chapterJob.failed_items} failed)`}
            </span>
          )}
        </div>
      )}

      <div style={{ border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 1fr 80px 110px 260px',
          padding: '10px 16px', backgroundColor: '#F9FAFB', fontSize: '11px',
          fontWeight: 600, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          <span>#</span>
          <span>Topic</span>
          <span>Count</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {topics.map((t, i) => {
          const topicStatus = getTopicStatus(t.guideline_id, t.question_count);
          const topicRunning = topicStatus === 'running';
          return (
            <div key={t.guideline_id} style={{
              display: 'grid', gridTemplateColumns: '40px 1fr 80px 110px 260px',
              padding: '10px 16px', borderTop: '1px solid #E5E7EB', alignItems: 'center',
              backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA',
            }}>
              <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{i + 1}</span>
              <span style={{ fontSize: '13px', fontWeight: 500 }}>{t.topic_title}</span>
              <span style={{ fontSize: '13px', color: t.question_count > 0 ? '#065F46' : '#9CA3AF', fontWeight: 600 }}>
                {t.question_count}
              </span>
              <TopicStatusBadge status={topicStatus} hasExplanations={t.has_explanations} />
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {!t.has_explanations ? (
                  <span style={{ fontSize: '11px', color: '#9CA3AF', fontStyle: 'italic' }}>
                    Needs explanations first
                  </span>
                ) : (
                  <>
                    <button onClick={() => handleGenerate(t.guideline_id)} disabled={topicRunning || t.question_count > 0} title={t.question_count > 0 ? 'Use Regenerate to overwrite existing bank' : 'Generate bank for this topic'} style={actionBtn('#0891B2', topicRunning || t.question_count > 0)}>
                      {topicRunning ? '...' : 'Generate'}
                    </button>
                    {t.question_count > 0 && (
                      <>
                        <button onClick={() => handleGenerate(t.guideline_id, true)} disabled={topicRunning} title="Delete existing bank and regenerate from scratch" style={actionBtn('#DC2626', topicRunning)}>
                          Regenerate
                        </button>
                        <button onClick={() => handleView(t.guideline_id)} title="View all questions in the bank" style={actionBtn('#2563EB', false)}>
                          View
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
            No approved topics in this chapter
          </div>
        )}
      </div>

      {viewing && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1000,
          display: 'flex', justifyContent: 'center', alignItems: 'center',
        }} onClick={() => setViewing(null)}>
          <div style={{
            backgroundColor: 'white', borderRadius: '12px', width: '95%', maxWidth: '1000px',
            maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: '16px' }}>{viewing.topic_title}</div>
                <div style={{ fontSize: '12px', color: '#6B7280' }}>
                  {viewing.question_count} question{viewing.question_count === 1 ? '' : 's'}
                </div>
              </div>
              <button onClick={() => setViewing(null)} style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {viewing.questions.map((q, i) => (
                <QuestionRow key={q.id} q={q} idx={i} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Status badge ─── */
const TopicStatusBadge: React.FC<{ status: string; hasExplanations: boolean }> = ({ status, hasExplanations }) => {
  if (!hasExplanations) {
    return <span style={{
      fontSize: '10px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
      backgroundColor: '#F3F4F6', color: '#9CA3AF',
    }}>no explanations</span>;
  }
  const map: Record<string, { bg: string; color: string; label: string }> = {
    running:       { bg: '#CCFBF1', color: '#115E59', label: 'running' },
    success:       { bg: '#D1FAE5', color: '#065F46', label: 'bank ready' },
    failed:        { bg: '#FEE2E2', color: '#991B1B', label: 'failed' },
    not_generated: { bg: '#F3F4F6', color: '#6B7280', label: 'not generated' },
  };
  const s = map[status] || map.not_generated;
  return <span style={{
    fontSize: '10px', fontWeight: 600, padding: '3px 8px', borderRadius: '10px',
    backgroundColor: s.bg, color: s.color,
  }}>{s.label}</span>;
};

function actionBtn(color: string, disabled: boolean): React.CSSProperties {
  return {
    backgroundColor: color, color: 'white', border: 'none',
    padding: '4px 10px', borderRadius: '4px', cursor: disabled ? 'wait' : 'pointer',
    fontSize: '11px', fontWeight: 600, opacity: disabled ? 0.5 : 1,
  };
}
