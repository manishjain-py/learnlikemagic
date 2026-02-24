import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCurriculum } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function SubjectSelect() {
  const navigate = useNavigate();
  const { country, board, grade } = useStudentProfile();
  const [subjects, setSubjects] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCurriculum({ country, board, grade })
      .then((res) => setSubjects(res.subjects || []))
      .catch((err) => console.error('Failed to fetch subjects:', err))
      .finally(() => setLoading(false));
  }, [country, board, grade]);

  return (
    <div className="selection-step">
      <h2>Select a Subject</h2>
      {loading ? (
        <p>Loading subjects...</p>
      ) : (
        <div className="selection-grid" data-testid="subject-list">
          {subjects.map((subject) => (
            <button
              key={subject}
              className="selection-card"
              data-testid="subject-item"
              onClick={() => navigate(`/learn/${encodeURIComponent(subject)}`)}
            >
              {subject}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
