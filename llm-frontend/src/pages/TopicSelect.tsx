import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function TopicSelect() {
  const navigate = useNavigate();
  const { subject } = useParams<{ subject: string }>();
  const { country, board, grade } = useStudentProfile();
  const [topics, setTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!subject) return;
    getCurriculum({ country, board, grade, subject })
      .then((res) => setTopics(res.topics || []))
      .catch((err) => console.error('Failed to fetch topics:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade, subject]);

  return (
    <div className="selection-step">
      <button className="back-button" onClick={() => navigate('/learn')}>
        &larr; Back
      </button>
      <h2>{subject} - Select a Topic</h2>
      {loading ? (
        <p>Loading topics...</p>
      ) : (
        <div className="selection-grid" data-testid="topic-list">
          {topics.map((topic) => (
            <button
              key={topic}
              className="selection-card"
              data-testid="topic-item"
              onClick={() => navigate(`/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(topic)}`)}
            >
              {topic}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
