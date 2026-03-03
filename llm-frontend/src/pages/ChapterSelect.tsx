import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getCurriculum } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function ChapterSelect() {
  const navigate = useNavigate();
  const { subject } = useParams<{ subject: string }>();
  const { country, board, grade } = useStudentProfile();
  const [chapters, setChapters] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!subject) return;
    getCurriculum({ country, board, grade, subject })
      .then((res) => setChapters(res.chapters || []))
      .catch((err) => console.error('Failed to fetch chapters:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade, subject]);

  return (
    <div className="selection-step">
      <button className="back-button" onClick={() => navigate('/learn')}>
        &larr; Back
      </button>
      <h2>{subject} - Select a Chapter</h2>
      {loading ? (
        <p>Loading chapters...</p>
      ) : (
        <div className="selection-grid" data-testid="chapter-list">
          {chapters.map((chapter) => (
            <button
              key={chapter}
              className="selection-card"
              data-testid="chapter-item"
              onClick={() => navigate(`/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter)}`)}
            >
              {chapter}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
