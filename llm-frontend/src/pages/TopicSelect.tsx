import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum, getTopicProgress, TopicInfo, TopicProgress } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function TopicSelect() {
  const navigate = useNavigate();
  const { subject, chapter } = useParams<{ subject: string; chapter: string }>();
  const { country, board, grade } = useStudentProfile();
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, TopicProgress>>({});
  const [loading, setLoading] = useState(true);

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

  const handleSelect = (st: TopicInfo) => {
    navigate(
      `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}/${encodeURIComponent(st.topic)}`,
      { state: { guidelineId: st.guideline_id } },
    );
  };

  return (
    <div className="selection-step">
      <button className="back-button" onClick={() => navigate(`/learn/${encodeURIComponent(subject!)}`)}>
        &larr; Back
      </button>
      <h2>
        {subject} &rarr; {chapter} - Select a Topic
      </h2>
      {loading ? (
        <p>Loading topics...</p>
      ) : (
        <div className="selection-grid" data-testid="topic-list">
          {topics.map((st) => (
            <button
              key={st.guideline_id}
              className="selection-card"
              data-testid="topic-item"
              onClick={() => handleSelect(st)}
            >
              {st.topic}
              {progress[st.guideline_id] && (
                <span className={`topic-status ${progress[st.guideline_id].status}`}>
                  {progress[st.guideline_id].status === 'studied' ? '\u2713' : '\u25CF'}
                  {' '}
                  {progress[st.guideline_id].coverage.toFixed(0)}%
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
