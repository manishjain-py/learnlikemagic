import React, { useState, useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import ModeSelection from '../components/ModeSelection';
import {
  createSession,
  getCurriculum,
  resumeSession as resumeSessionAPI,
  SubtopicInfo,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

export default function ModeSelectPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { subject, topic, subtopic } = useParams<{ subject: string; topic: string; subtopic: string }>();
  const { country, board, grade, studentId } = useStudentProfile();

  const [guidelineId, setGuidelineId] = useState<string | null>(
    (location.state as any)?.guidelineId || null,
  );
  const [loading, setLoading] = useState(!guidelineId);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [creatingMode, setCreatingMode] = useState<'teach_me' | 'clarify_doubts' | 'exam' | null>(null);

  // For deep links: if no guidelineId in location state, fetch it
  useEffect(() => {
    if (guidelineId || !subject || !topic) return;
    getCurriculum({ country, board, grade, subject, topic })
      .then((res) => {
        const match = (res.subtopics || []).find((st) => st.subtopic === subtopic);
        if (match) setGuidelineId(match.guideline_id);
      })
      .catch((err) => console.error('Failed to resolve guideline:', err))
      .finally(() => setLoading(false));
  }, [guidelineId, country, board, grade, subject, topic, subtopic]);

  if (loading || !guidelineId) {
    return (
      <div className="selection-step">
        <p>Loading...</p>
      </div>
    );
  }

  const subtopicInfo: SubtopicInfo = { subtopic: subtopic!, guideline_id: guidelineId };

  const handleModeSelect = async (mode: 'teach_me' | 'clarify_doubts' | 'exam') => {
    setSessionError(null);
    setCreatingMode(mode);
    try {
      const response = await createSession({
        student: {
          id: studentId,
          grade,
          prefs: { style: 'standard', lang: 'en' },
        },
        goal: {
          topic: topic!,
          syllabus: `${board}-G${grade}`,
          learning_objectives: [`Learn ${subtopic}`],
          guideline_id: guidelineId,
        },
        mode,
      });
      navigate(`/session/${response.session_id}`, {
        state: { firstTurn: response.first_turn, mode, subject, topic, subtopic },
      });
    } catch (error: any) {
      console.error('Failed to start session:', error);
      setSessionError(error?.message || 'Failed to start session. Please try again.');
      setCreatingMode(null);
    }
  };

  const handleResume = async (resumeSessionId: string) => {
    setSessionError(null);
    try {
      const result = await resumeSessionAPI(resumeSessionId);
      navigate(`/session/${resumeSessionId}`, {
        state: {
          conversationHistory: result.conversation_history,
          currentStep: result.current_step,
          mode: 'teach_me',
          subject,
          topic,
          subtopic,
        },
      });
    } catch (error: any) {
      console.error('Failed to resume session:', error);
      setSessionError(error?.message || 'Failed to resume session. Please try again.');
    }
  };

  const handleBack = () => {
    navigate(`/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(topic!)}`);
  };

  return (
    <>
      {sessionError && (
        <div style={{
          background: '#fee2e2',
          color: '#991b1b',
          padding: '12px 16px',
          borderRadius: '8px',
          marginBottom: '16px',
          fontSize: '0.9rem',
        }}>
          {sessionError}
        </div>
      )}
      <ModeSelection
        subtopic={subtopicInfo}
        onSelectMode={handleModeSelect}
        onResume={handleResume}
        onBack={handleBack}
        creatingMode={creatingMode}
      />
    </>
  );
}
