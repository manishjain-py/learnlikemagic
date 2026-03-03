import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum, getTopicProgress, TopicInfo, TopicProgress } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

type ProgressStatus = 'completed' | 'in_progress' | 'not_started';

export default function TopicSelect() {
  const navigate = useNavigate();
  const { subject, chapter } = useParams<{ subject: string; chapter: string }>();
  const { country, board, grade } = useStudentProfile();
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, TopicProgress>>({});
  const [loading, setLoading] = useState(true);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!subject || !chapter) return;
    Promise.all([
      getCurriculum({ country, board, grade, subject, chapter }),
      getTopicProgress().catch(() => ({})),
    ])
      .then(([currRes, prog]) => {
        setTopics(currRes.topics || []);
        setProgress(prog as Record<string, TopicProgress>);
      })
      .catch((err) => console.error('Failed to fetch topics:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade, subject, chapter]);

  const getTopicStatus = (t: TopicInfo): ProgressStatus => {
    const p = progress[t.guideline_id];
    if (!p || p.coverage === 0) return 'not_started';
    if (p.coverage >= 80) return 'completed';
    return 'in_progress';
  };

  const handleSelect = (t: TopicInfo) => {
    navigate(
      `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}/${encodeURIComponent(t.topic)}`,
      { state: { guidelineId: t.guideline_id } },
    );
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
        <button
          className="breadcrumb-link"
          onClick={() => navigate(`/learn/${encodeURIComponent(subject!)}`)}
        >
          {subject}
        </button>
        <span className="breadcrumb-sep">&rsaquo;</span>
        <span className="breadcrumb-current">{chapter}</span>
      </div>

      <h2>Topics</h2>

      {loading ? (
        <p>Loading topics...</p>
      ) : (
        <div className="learning-path" data-testid="topic-list">
          {topics.map((t, idx) => {
            const status = getTopicStatus(t);
            const cov = progress[t.guideline_id]?.coverage ?? 0;
            const isExpanded = expandedIdx === idx;
            return (
              <button
                key={t.guideline_id}
                className={`learning-path-item learning-path-item--${status}`}
                data-testid="topic-item"
                onClick={() => handleSelect(t)}
              >
                <div className="learning-path-number">
                  <span className={`step-circle step-circle--${status}`}>
                    {status === 'completed' ? '\u2713' : idx + 1}
                  </span>
                </div>
                <div className="learning-path-content">
                  <div className="learning-path-title">{t.topic}</div>
                  <div className="learning-path-meta">
                    {cov > 0 && <span>{cov.toFixed(0)}% covered</span>}
                    {t.topic_summary && (
                      <span
                        className="info-toggle"
                        onClick={(e) => toggleSummary(e, idx)}
                      >
                        {isExpanded ? 'Hide info' : 'Info'}
                      </span>
                    )}
                  </div>
                  {isExpanded && t.topic_summary && (
                    <div className="learning-path-summary">{t.topic_summary}</div>
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
