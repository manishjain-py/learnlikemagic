import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCurriculum, getEnrichmentProfile } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';
import { useAuth } from '../contexts/AuthContext';

export default function SubjectSelect() {
  const navigate = useNavigate();
  const { country, board, grade, studentName } = useStudentProfile();
  const { user } = useAuth();
  const [subjects, setSubjects] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [showEnrichmentPrompt, setShowEnrichmentPrompt] = useState(false);

  useEffect(() => {
    getCurriculum({ country, board, grade })
      .then((res) => setSubjects(res.subjects || []))
      .catch((err) => console.error('Failed to fetch subjects:', err))
      .finally(() => setLoading(false));

    // Check if enrichment profile is empty
    getEnrichmentProfile()
      .then((profile) => {
        if (profile.sections_filled === 0) {
          setShowEnrichmentPrompt(true);
        }
      })
      .catch(() => {}); // Silently ignore if endpoint not available
  }, [country, board, grade]);

  const kidName = user?.preferred_name || user?.name || 'your child';

  return (
    <div className="selection-step">
      {showEnrichmentPrompt && (
        <div
          className="enrichment-home-prompt"
          onClick={() => navigate('/profile/enrichment')}
        >
          <span>{kidName}'s learning profile is empty &mdash; help us personalize their experience!</span>
          <button
            className="enrichment-home-dismiss"
            onClick={(e) => { e.stopPropagation(); setShowEnrichmentPrompt(false); }}
          >
            x
          </button>
        </div>
      )}
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
