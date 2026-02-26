import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum, getSubtopicProgress, SubtopicInfo, SubtopicProgress } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function SubtopicSelect() {
  const navigate = useNavigate();
  const { subject, topic } = useParams<{ subject: string; topic: string }>();
  const { country, board, grade } = useStudentProfile();
  const [subtopics, setSubtopics] = useState<SubtopicInfo[]>([]);
  const [progress, setProgress] = useState<Record<string, SubtopicProgress>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!subject || !topic) return;
    Promise.all([
      getCurriculum({ country, board, grade, subject, topic }),
      getSubtopicProgress().catch(() => ({})),
    ])
      .then(([currRes, prog]) => {
        setSubtopics(currRes.subtopics || []);
        setProgress(prog as Record<string, SubtopicProgress>);
      })
      .catch((err) => console.error('Failed to fetch subtopics:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade, subject, topic]);

  const handleSelect = (st: SubtopicInfo) => {
    navigate(
      `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(topic!)}/${encodeURIComponent(st.subtopic)}`,
      { state: { guidelineId: st.guideline_id } },
    );
  };

  return (
    <div className="selection-step">
      <button className="back-button" onClick={() => navigate(`/learn/${encodeURIComponent(subject!)}`)}>
        &larr; Back
      </button>
      <h2>
        {subject} &rarr; {topic} - Select a Subtopic
      </h2>
      {loading ? (
        <p>Loading subtopics...</p>
      ) : (
        <div className="selection-grid" data-testid="subtopic-list">
          {subtopics.map((st) => (
            <button
              key={st.guideline_id}
              className="selection-card"
              data-testid="subtopic-item"
              onClick={() => handleSelect(st)}
            >
              {st.subtopic}
              {progress[st.guideline_id] && (
                <span className={`subtopic-status ${progress[st.guideline_id].status}`}>
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
