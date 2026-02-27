import React, { useEffect, useState } from 'react';
import { getResumableSession, ResumableSession, SubtopicInfo } from '../api';

const MODE_LOADING_MESSAGES: Record<string, string> = {
  teach_me: 'Setting up your lesson...',
  clarify_doubts: 'Getting ready for your questions...',
  exam: 'Preparing your question paper...',
};

interface ModeSelectionProps {
  subtopic: SubtopicInfo;
  onSelectMode: (mode: 'teach_me' | 'clarify_doubts' | 'exam') => void;
  onResume: (sessionId: string) => void;
  onBack: () => void;
  creatingMode?: 'teach_me' | 'clarify_doubts' | 'exam' | null;
}

function ModeSelection({ subtopic, onSelectMode, onResume, onBack, creatingMode }: ModeSelectionProps) {
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

      {creatingMode ? (
        <div style={{ textAlign: 'center', padding: '32px 16px' }}>
          <div className="typing-indicator" style={{ justifyContent: 'center', marginBottom: '16px' }}>
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p style={{ fontSize: '1.1rem', fontWeight: 500, color: '#4a5568' }}>
            {MODE_LOADING_MESSAGES[creatingMode]}
          </p>
          <p style={{ fontSize: '0.85rem', color: '#999', marginTop: '8px' }}>
            This may take a moment
          </p>
        </div>
      ) : loading ? (
        <p>Loading...</p>
      ) : (
        <div className="selection-grid" data-testid="mode-selection" style={{ gridTemplateColumns: '1fr' }}>
          <button className="selection-card" data-testid="mode-teach-me" onClick={() => onSelectMode('teach_me')}>
            <strong>Teach Me</strong>
            <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
              Learn this topic from scratch
            </span>
          </button>
          <button className="selection-card" data-testid="mode-clarify-doubts" onClick={() => onSelectMode('clarify_doubts')}>
            <strong>Clarify Doubts</strong>
            <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
              I have questions about this topic
            </span>
          </button>
          <button className="selection-card" data-testid="mode-exam" onClick={() => onSelectMode('exam')}>
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
