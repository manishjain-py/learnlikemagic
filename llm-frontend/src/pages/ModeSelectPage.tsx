import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import ModeSelection from '../components/ModeSelection';
import {
  createSession,
  getCurriculum,
  getPracticeAvailability,
  PracticeAvailability,
  TopicInfo,
  SessionConflictError,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

const MODE_URL_SEGMENT: Record<string, string> = {
  teach_me: 'teach',
  clarify_doubts: 'clarify',
};

// URL topic segments are slugs (e.g. "comparing-like-denominators"); convert
// to a display title when the backend doesn't give us a human-readable one.
function humanizeTopicSlug(slug: string): string {
  if (!slug) return slug;
  if (!/[-_]/.test(slug)) return slug; // already human-readable
  return slug
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

type SelectableMode = 'teach_me' | 'clarify_doubts';

export default function ModeSelectPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { subject, chapter, topic } = useParams<{ subject: string; chapter: string; topic: string }>();
  const { country, board, grade, studentId } = useStudentProfile();

  const [guidelineId, setGuidelineId] = useState<string | null>(
    (location.state as any)?.guidelineId || null,
  );
  const [resolvedTopicKey, setResolvedTopicKey] = useState<string | null>(
    (location.state as any)?.topicKey || null,
  );
  const [loading, setLoading] = useState(!guidelineId);
  const [availability, setAvailability] = useState<PracticeAvailability | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [creatingMode, setCreatingMode] = useState<SelectableMode | null>(null);
  const autostartFiredRef = useRef(false);

  // Deep-link fallback: resolve guidelineId from URL params if not in state.
  useEffect(() => {
    if (guidelineId || !subject || !chapter) return;
    getCurriculum({ country, board, grade, subject, chapter })
      .then((res) => {
        const match = (res.topics || []).find((st) => st.topic === topic);
        if (match) {
          setGuidelineId(match.guideline_id);
          setResolvedTopicKey(match.topic_key);
        }
      })
      .catch((err) => console.error('Failed to resolve guideline:', err))
      .finally(() => setLoading(false));
  }, [guidelineId, country, board, grade, subject, chapter, topic]);

  // Fetch practice-bank availability once guidelineId is known — drives the
  // Let's Practice tile's enabled state.
  useEffect(() => {
    if (!guidelineId) return;
    getPracticeAvailability(guidelineId)
      .then(setAvailability)
      .catch(() => setAvailability({ available: false, question_count: 0 }));
  }, [guidelineId]);

  const buildSessionUrl = (mode: string, sessionId: string) => {
    const seg = MODE_URL_SEGMENT[mode] || mode;
    return `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}/${encodeURIComponent(topic!)}/${seg}/${sessionId}`;
  };

  const handleModeSelect = async (mode: SelectableMode) => {
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
          chapter: chapter!,
          syllabus: `${board}-G${grade}`,
          learning_objectives: [`Learn ${topic}`],
          guideline_id: guidelineId!,
        },
        mode,
      });
      navigate(buildSessionUrl(mode, response.session_id), {
        state: { firstTurn: response.first_turn, mode, topicKey: resolvedTopicKey },
      });
    } catch (error: any) {
      console.error('Failed to start session:', error);
      if (error instanceof SessionConflictError) {
        navigate(buildSessionUrl(mode, error.existing_session_id));
        return;
      }
      setSessionError(error?.message || 'Failed to start session. Please try again.');
      setCreatingMode(null);
    }
  };

  // ?autostart=teach_me support — fired once after guidelineId is resolved,
  // e.g. from the Reteach CTA on PracticeResultsPage. Clear the query via
  // replace so a browser-back returns to a clean mode-select URL.
  useEffect(() => {
    if (autostartFiredRef.current) return;
    if (!guidelineId) return;
    const autostart = new URLSearchParams(location.search).get('autostart');
    if (autostart !== 'teach_me') return;
    autostartFiredRef.current = true;
    navigate(location.pathname, { replace: true });
    handleModeSelect('teach_me');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guidelineId, location.search]);

  if (loading || !guidelineId) {
    return (
      <div className="selection-step">
        <p>Loading...</p>
      </div>
    );
  }

  const topicInfo: TopicInfo = { topic: topic!, guideline_id: guidelineId, topic_key: resolvedTopicKey, topic_summary: null, topic_sequence: null };

  const handleResume = (sessionId: string, mode: string) => {
    navigate(buildSessionUrl(mode, sessionId));
  };

  const handlePractice = () => {
    navigate(`/practice/${guidelineId}`, {
      state: {
        topicTitle: humanizeTopicSlug(topic!),
        subject,
        chapter,
        topic,
        topicKey: resolvedTopicKey,
      },
    });
  };

  const handleBack = () => {
    navigate(`/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}`);
  };

  return (
    <>
      {sessionError && (
        <div className="session-error-banner" role="alert" aria-live="assertive">
          {sessionError}
        </div>
      )}
      <ModeSelection
        topic={topicInfo}
        onSelectMode={handleModeSelect}
        onResume={handleResume}
        onBack={handleBack}
        onPractice={handlePractice}
        practiceAvailable={availability?.available ?? false}
        creatingMode={creatingMode}
      />
    </>
  );
}
