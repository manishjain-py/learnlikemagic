import React, { useEffect, useState } from 'react';
import { getResumableSession, ResumableSession, SubtopicInfo } from '../api';

interface ModeSelectionProps {
  subtopic: SubtopicInfo;
  onSelectMode: (mode: 'teach_me' | 'clarify_doubts' | 'exam') => void;
  onResume: (sessionId: string) => void;
  onBack: () => void;
}

function ModeSelection({ subtopic, onSelectMode, onResume, onBack }: ModeSelectionProps) {
  const [resumable, setResumable] = useState<ResumableSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getResumableSession(subtopic.guideline_id)
      .then(setResumable)
      .catch(() => setResumable(null))
      .finally(() => setLoading(false));
  }, [subtopic.guideline_id]);

  return (
    <div className="selection-step">
      <button className="back-button" onClick={onBack}>
        ← Back
      </button>
      <h2>{subtopic.subtopic}</h2>
      <p style={{ color: '#666', marginBottom: '20px' }}>What would you like to do?</p>

      {resumable && (
        <button
          className="selection-card resume-card"
          onClick={() => onResume(resumable.session_id)}
          style={{
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: 'white',
            marginBottom: '16px',
            width: '100%',
          }}
        >
          <strong>Resume</strong>
          <span style={{ display: 'block', fontSize: '0.85rem', marginTop: '4px' }}>
            {resumable.coverage.toFixed(0)}% covered — pick up where you left off
          </span>
        </button>
      )}

      {loading ? (
        <p>Loading...</p>
      ) : (
        <div className="selection-grid" style={{ gridTemplateColumns: '1fr' }}>
          <button className="selection-card" onClick={() => onSelectMode('teach_me')}>
            <strong>Teach Me</strong>
            <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
              Learn this topic from scratch
            </span>
          </button>
          <button className="selection-card" onClick={() => onSelectMode('clarify_doubts')}>
            <strong>Clarify Doubts</strong>
            <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
              I have questions about this topic
            </span>
          </button>
          <button className="selection-card" onClick={() => onSelectMode('exam')}>
            <strong>Exam</strong>
            <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
              Test my knowledge
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

export default ModeSelection;
