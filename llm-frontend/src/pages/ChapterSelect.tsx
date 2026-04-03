import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum, getTopicProgress, ChapterInfo, TopicProgress } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

type ProgressStatus = 'completed' | 'in_progress' | 'not_started';

export default function ChapterSelect() {
  const navigate = useNavigate();
  const { subject } = useParams<{ subject: string }>();
  const { country, board, grade } = useStudentProfile();
  const [chapters, setChapters] = useState<ChapterInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, TopicProgress>>({});
  const [loading, setLoading] = useState(true);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!subject) return;
    Promise.all([
      getCurriculum({ country, board, grade, subject }),
      getTopicProgress().catch(() => ({})),
    ])
      .then(([currRes, prog]) => {
        setChapters(currRes.chapters || []);
        setProgress(prog as Record<string, TopicProgress>);
      })
      .catch((err) => console.error('Failed to fetch chapters:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade, subject]);

  const getChapterStatus = (ch: ChapterInfo): ProgressStatus => {
    // Exclude refresher topic from progress calculation
    const progressIds = ch.refresher_guideline_id
      ? ch.guideline_ids.filter((id) => id !== ch.refresher_guideline_id)
      : ch.guideline_ids;
    if (progressIds.length === 0) return 'not_started';
    const coverages = progressIds.map((id) => progress[id]?.coverage ?? 0);
    const avg = coverages.reduce((a, b) => a + b, 0) / coverages.length;
    if (avg >= 80) return 'completed';
    if (avg > 0) return 'in_progress';
    return 'not_started';
  };

  const toggleSummary = (e: React.MouseEvent, idx: number) => {
    e.stopPropagation();
    setExpandedIdx(expandedIdx === idx ? null : idx);
  };

  return (
    <div className="selection-step">
      <div className="breadcrumb">
        <button className="breadcrumb-link" onClick={() => navigate('/learn')}>
          Subjects
        </button>
        <span className="breadcrumb-sep">&rsaquo;</span>
        <span className="breadcrumb-current">{subject}</span>
      </div>

      <h2>Chapters</h2>

      {loading ? (
        <p>Loading chapters...</p>
      ) : (
        <div className="learning-path" data-testid="chapter-list">
          {chapters.map((ch, idx) => {
            const status = getChapterStatus(ch);
            const isExpanded = expandedIdx === idx;
            return (
              <button
                key={ch.chapter}
                className={`learning-path-item learning-path-item--${status}`}
                data-testid="chapter-item"
                onClick={() =>
                  navigate(
                    `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(ch.chapter)}`,
                    { state: { chapterSummary: ch.chapter_summary } },
                  )
                }
              >
                <div className="learning-path-number">
                  <span className={`step-circle step-circle--${status}`}>
                    {status === 'completed' ? '\u2713' : idx + 1}
                  </span>
                </div>
                <div className="learning-path-content">
                  <div className="learning-path-title">{ch.chapter}</div>
                  <div className="learning-path-meta">
                    {ch.refresher_guideline_id ? ch.topic_count - 1 : ch.topic_count} topic{(ch.refresher_guideline_id ? ch.topic_count - 1 : ch.topic_count) !== 1 ? 's' : ''}
                    {ch.chapter_summary && (
                      <span
                        className="info-toggle"
                        onClick={(e) => toggleSummary(e, idx)}
                      >
                        {isExpanded ? 'Hide info' : 'Info'}
                      </span>
                    )}
                  </div>
                  {isExpanded && ch.chapter_summary && (
                    <div className="learning-path-summary">{ch.chapter_summary}</div>
                  )}
                </div>
                <div className="learning-path-arrow">&rsaquo;</div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
