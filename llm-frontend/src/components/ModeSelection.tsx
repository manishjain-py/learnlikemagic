import React, { useEffect, useState } from 'react';
import { getGuidelineSessions, GuidelineSessionEntry, SubtopicInfo } from '../api';

const MODE_LOADING_MESSAGES: Record<string, string> = {
  teach_me: 'Setting up your lesson...',
  clarify_doubts: 'Getting ready for your questions...',
  exam: 'Preparing your question paper...',
};

interface ModeSelectionProps {
  subtopic: SubtopicInfo;
  onSelectMode: (mode: 'teach_me' | 'clarify_doubts' | 'exam') => void;
  onResume: (sessionId: string, mode: string) => void;
  onBack: () => void;
  onViewExamReview: (sessionId: string) => void;
  creatingMode?: 'teach_me' | 'clarify_doubts' | 'exam' | null;
}

function ModeSelection({ subtopic, onSelectMode, onResume, onBack, onViewExamReview, creatingMode }: ModeSelectionProps) {
  const [sessions, setSessions] = useState<GuidelineSessionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPastExams, setShowPastExams] = useState(false);

  useEffect(() => {
    getGuidelineSessions(subtopic.guideline_id)
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, [subtopic.guideline_id]);

  // Find incomplete sessions for resume — only show if there's actual progress
  const incompleteExam = sessions.find((s) => s.mode === 'exam' && !s.is_complete && (s.exam_answered ?? 0) > 0);
  const incompleteTeachMe = sessions.find((s) => s.mode === 'teach_me' && !s.is_complete && (s.coverage ?? 0) > 0);

  // Completed exams for past exams section
  const completedExams = sessions.filter((s) => s.mode === 'exam' && s.is_complete);

  return (
    <div className="selection-step">
      <button className="back-button" onClick={onBack}>
        ← Back
      </button>
      <h2>{subtopic.subtopic}</h2>
      <p style={{ color: '#666', marginBottom: '20px' }}>What would you like to do?</p>

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
        <>
          {/* Resume cards */}
          {incompleteTeachMe && (
            <button
              className="selection-card resume-card"
              onClick={() => onResume(incompleteTeachMe.session_id, 'teach_me')}
              style={{
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white',
                marginBottom: '10px',
                width: '100%',
              }}
            >
              <strong>Resume Lesson</strong>
              <span style={{ display: 'block', fontSize: '0.85rem', marginTop: '4px' }}>
                {incompleteTeachMe.coverage != null ? `${incompleteTeachMe.coverage.toFixed(0)}% covered` : 'In progress'} — pick up where you left off
              </span>
            </button>
          )}

          {incompleteExam && (
            <button
              className="selection-card resume-card"
              onClick={() => onResume(incompleteExam.session_id, 'exam')}
              style={{
                background: 'linear-gradient(135deg, #ed8936 0%, #dd6b20 100%)',
                color: 'white',
                marginBottom: '10px',
                width: '100%',
              }}
            >
              <strong>Resume Exam</strong>
              <span style={{ display: 'block', fontSize: '0.85rem', marginTop: '4px' }}>
                {incompleteExam.exam_answered != null && incompleteExam.exam_total != null
                  ? `${incompleteExam.exam_answered}/${incompleteExam.exam_total} answered`
                  : 'In progress'} — continue your exam
              </span>
            </button>
          )}

          <div className="selection-grid" data-testid="mode-selection" style={{ gridTemplateColumns: '1fr' }}>
            {!incompleteTeachMe && (
              <button className="selection-card" data-testid="mode-teach-me" onClick={() => onSelectMode('teach_me')}>
                <strong>Teach Me</strong>
                <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
                  Learn this topic from scratch
                </span>
              </button>
            )}
            <button className="selection-card" data-testid="mode-clarify-doubts" onClick={() => onSelectMode('clarify_doubts')}>
              <strong>Clarify Doubts</strong>
              <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
                I have questions about this topic
              </span>
            </button>
            {!incompleteExam && (
              <button className="selection-card" data-testid="mode-exam" onClick={() => onSelectMode('exam')}>
                <strong>Take Exam</strong>
                <span style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginTop: '4px' }}>
                  Test my knowledge
                </span>
              </button>
            )}
          </div>

          {/* Past exams section */}
          {completedExams.length > 0 && (
            <div style={{ marginTop: '20px' }}>
              <button
                onClick={() => setShowPastExams(!showPastExams)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#667eea',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                {showPastExams ? '\u25BC' : '\u25B6'} Past Exams ({completedExams.length})
              </button>
              {showPastExams && (
                <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {completedExams.map((exam) => {
                    const score = exam.exam_score ?? 0;
                    const total = exam.exam_total ?? 0;
                    const pct = total > 0 ? (score / total) * 100 : 0;
                    const scoreColor = pct >= 70 ? '#38a169' : pct >= 40 ? '#dd6b20' : '#e53e3e';
                    return (
                      <button
                        key={exam.session_id}
                        onClick={() => onViewExamReview(exam.session_id)}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          padding: '10px 14px',
                          background: '#fafafa',
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          cursor: 'pointer',
                          width: '100%',
                          textAlign: 'left',
                        }}
                      >
                        <span style={{ fontSize: '0.85rem', color: '#4a5568' }}>
                          {exam.created_at
                            ? new Date(exam.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                            : 'Exam'}
                        </span>
                        <span style={{ fontWeight: 700, color: scoreColor, fontSize: '0.9rem' }}>
                          {score % 1 === 0 ? score.toFixed(0) : score.toFixed(1)}/{total} ({pct.toFixed(0)}%)
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ModeSelection;
