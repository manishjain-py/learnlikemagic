/**
 * TeachMeSubChooser — sub-step between mode selection and the session for
 * Teach Me. Two cards: Baatcheet (recommended) on top, Explain (existing
 * flow) below. Each card surfaces availability + resume CTA + (Baatcheet
 * only) a stale badge driven by `is_stale` from the aggregator endpoint.
 *
 * No memory of last choice — student picks every entry (PRD §FR-2).
 */
import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  createSession,
  getCurriculum,
  getTeachMeOptions,
  type TeachMeMode,
  type TeachMeOptionsResponse,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';

const MODE_URL_SEGMENT: Record<string, string> = {
  teach_me: 'teach',
  clarify_doubts: 'clarify',
};

export default function TeachMeSubChooser() {
  const navigate = useNavigate();
  const location = useLocation();
  const { subject, chapter, topic } = useParams<{
    subject: string; chapter: string; topic: string;
  }>();
  const { country, board, grade, studentId } = useStudentProfile();

  const initial = (location.state as any) || {};
  const [guidelineId, setGuidelineId] = useState<string | null>(initial.guidelineId || null);
  const [resolvedTopicKey, setResolvedTopicKey] = useState<string | null>(initial.topicKey || null);
  const [options, setOptions] = useState<TeachMeOptionsResponse | null>(null);
  const [loading, setLoading] = useState(!initial.guidelineId);
  const [error, setError] = useState<string | null>(null);
  const [creatingMode, setCreatingMode] = useState<TeachMeMode | null>(null);

  // Deep-link fallback: resolve guidelineId if the page is hit cold.
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

  // Fetch availability + in-progress + stale flags for both submodes.
  useEffect(() => {
    if (!guidelineId) return;
    getTeachMeOptions(guidelineId)
      .then(setOptions)
      .catch((err) => {
        console.error('Failed to fetch teach-me options:', err);
        setError('Could not load options. Try again?');
      });
  }, [guidelineId]);

  const buildSessionUrl = (sessionId: string) => (
    `/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}/${encodeURIComponent(topic!)}/${MODE_URL_SEGMENT.teach_me}/${sessionId}`
  );

  const startOrResume = async (subMode: TeachMeMode) => {
    if (!guidelineId) return;
    const opt = subMode === 'baatcheet' ? options?.baatcheet : options?.explain;
    if (opt?.in_progress_session_id) {
      navigate(buildSessionUrl(opt.in_progress_session_id));
      return;
    }
    setError(null);
    setCreatingMode(subMode);
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
          guideline_id: guidelineId,
        },
        mode: 'teach_me',
        teach_me_mode: subMode,
      });
      navigate(buildSessionUrl(response.session_id), {
        state: {
          firstTurn: response.first_turn,
          mode: 'teach_me',
          teachMeMode: response.teach_me_mode || subMode,
          topicKey: resolvedTopicKey,
        },
      });
    } catch (err: any) {
      console.error('Failed to start session:', err);
      setError(err?.message || 'Could not start session. Please try again.');
      setCreatingMode(null);
    }
  };

  const handleBack = () => {
    navigate(`/learn/${encodeURIComponent(subject!)}/${encodeURIComponent(chapter!)}/${encodeURIComponent(topic!)}`);
  };

  if (loading || !guidelineId) {
    return (
      <div className="selection-step">
        <p>Loading…</p>
      </div>
    );
  }

  const baatcheetAvailable = options?.baatcheet.available ?? false;
  const baatcheetStale = options?.baatcheet.is_stale ?? false;
  const baatcheetProgress = options?.baatcheet;
  const explainProgress = options?.explain;

  return (
    <div className="selection-step">
      <button type="button" className="back-button" onClick={handleBack}>
        ← Back
      </button>
      <h2 className="selection-step__title">How do you want to learn?</h2>
      {error && (
        <div className="session-error-banner" role="alert" aria-live="assertive">
          {error}
        </div>
      )}
      <div className="mode-cards">
        {/* Baatcheet — recommended, visually emphasized */}
        <button
          type="button"
          className={`selection-card baatcheet-card ${baatcheetAvailable ? '' : 'is-disabled'}`}
          onClick={() => baatcheetAvailable && startOrResume('baatcheet')}
          disabled={!baatcheetAvailable || creatingMode !== null}
          aria-label="Baatcheet (recommended)"
        >
          <span className="badge">Recommended</span>
          <strong className="mode-card-title">Baatcheet</strong>
          {baatcheetAvailable ? (
            baatcheetProgress?.in_progress_session_id ? (
              <span className="mode-card-sub">
                Continue — {(baatcheetProgress?.current_card_idx ?? 0) + 1} / {baatcheetProgress?.total_cards ?? '?'}
              </span>
            ) : baatcheetProgress?.completed_session_id ? (
              <span className="mode-card-sub">Completed — start again?</span>
            ) : (
              <span className="mode-card-sub">
                Listen in on a friendly chat about this topic
              </span>
            )
          ) : (
            <span className="mode-card-sub">Coming soon</span>
          )}
          {baatcheetStale && (
            <span className="mode-card-stale" title="Variant A has changed since this dialogue was generated">
              ⚠ Out of date — admin should regenerate
            </span>
          )}
          {creatingMode === 'baatcheet' && (
            <span className="mode-card-sub">Starting…</span>
          )}
        </button>

        {/* Explain — existing flow, visually quieter secondary */}
        <button
          type="button"
          className="selection-card explain-card"
          onClick={() => startOrResume('explain')}
          disabled={creatingMode !== null}
          aria-label="Explain mode"
        >
          <strong className="mode-card-title">Explain</strong>
          {explainProgress?.in_progress_session_id ? (
            <span className="mode-card-sub">
              Continue — {(explainProgress?.current_card_idx ?? 0) + 1} / {explainProgress?.total_cards ?? '?'}
            </span>
          ) : explainProgress?.completed_session_id ? (
            <span className="mode-card-sub">Completed — review again?</span>
          ) : (
            <span className="mode-card-sub">Step-by-step explanation cards</span>
          )}
          {creatingMode === 'explain' && (
            <span className="mode-card-sub">Starting…</span>
          )}
        </button>
      </div>
    </div>
  );
}
