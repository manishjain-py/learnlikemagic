/**
 * BaatcheetViewer — renders a Baatcheet (Mr. Verma + Meera) dialogue.
 *
 * Self-contained sibling to ChatSession's ExplanationViewer (which still
 * lives inline in ChatSession.tsx — extraction deferred). Owns:
 *   - carousel state (current_card_idx)
 *   - SpeakerAvatar cross-fade per turn
 *   - audio playback (pre-rendered MP3 OR synthetic-key blob for personalized)
 *   - check-in dispatch (reuses CheckInDispatcher)
 *   - server-side progress posting (debounced) + summary completion mark
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  postCardProgress,
  type CardProgressResponse,
  type DialogueCard,
  type Personalization,
} from '../../api';
import {
  getCachedBlob,
  getClientAudioBlob,
  prefetchAudio,
  registerAudioStop,
  stopAllAudio,
} from '../../hooks/audioController';
import {
  personalizedAudioKey,
  usePersonalizedAudio,
} from '../../hooks/usePersonalizedAudio';
import SpeakerAvatar from '../baatcheet/SpeakerAvatar';
import CheckInDispatcher, {
  type CheckInActivityResult,
} from '../CheckInDispatcher';
import VisualExplanationComponent from '../VisualExplanation';

interface Props {
  sessionId: string;
  cards: DialogueCard[];
  personalization: Personalization;
  initialCardIdx?: number;
  language?: string;
  onComplete?: (info: CardProgressResponse) => void;
}

const PROGRESS_DEBOUNCE_MS = 500;

function materializeText(text: string, p: Personalization): string {
  const name = (p.student_name || '').trim() || p.fallback_student_name || 'friend';
  return text
    .replaceAll('{student_name}', name)
    .replaceAll('{topic_name}', p.topic_name);
}

export default function BaatcheetViewer({
  sessionId,
  cards,
  personalization,
  initialCardIdx = 0,
  language = 'hinglish',
  onComplete,
}: Props) {
  const totalCards = cards.length;
  const [cardIdx, setCardIdx] = useState(() =>
    Math.max(0, Math.min(initialCardIdx, Math.max(0, totalCards - 1))),
  );
  // Don't pre-seed `visited` with `initialCardIdx`. The post-effect below
  // marks cards visited after their first playback, so the welcome card (or
  // a resumed card) still triggers auto-play on mount.
  const [visited, setVisited] = useState<Set<number>>(() => new Set());
  const [speaking, setSpeaking] = useState(false);
  const [completed, setCompleted] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const debounceRef = useRef<number | null>(null);

  // Kick off runtime TTS for personalized cards in parallel (cap 4).
  usePersonalizedAudio(cards, personalization, language);

  // Warm the blob cache for every pre-rendered audio_url on the deck.
  useEffect(() => {
    cards.forEach((card) => {
      if (card.includes_student_name) return;
      card.lines.forEach((l) => prefetchAudio(l.audio_url));
      const ci = card.check_in;
      if (ci) {
        prefetchAudio(ci.audio_text_url);
        prefetchAudio(ci.hint_audio_url);
        prefetchAudio(ci.success_audio_url);
        prefetchAudio(ci.reveal_audio_url);
      }
    });
  }, [cards]);

  const currentCard = cards[cardIdx];

  // ─── Audio playback ────────────────────────────────────────────────────
  // Plays each line of the current card sequentially. Auto-plays the first
  // time a card is visited; revisited cards stay silent (PRD §FR-31).
  useEffect(() => {
    if (!currentCard) return;
    const isFirstVisit = !visited.has(cardIdx);
    if (!isFirstVisit) return;
    if (currentCard.card_type === 'check_in') {
      // CheckInDispatcher handles its own audio.
      return;
    }

    let cancelled = false;
    let cleanup: (() => void) | null = null;
    setSpeaking(true);

    (async () => {
      for (let lineIdx = 0; lineIdx < currentCard.lines.length; lineIdx++) {
        if (cancelled) break;
        const line = currentCard.lines[lineIdx];

        let blob: Blob | null = null;
        if (currentCard.includes_student_name) {
          // Personalized audio is synthesized in the background by
          // usePersonalizedAudio. The synth may not be done by the time the
          // playback effect first runs — wait briefly for the blob to arrive
          // before falling through to silent skip.
          const key = personalizedAudioKey(currentCard.card_id, lineIdx);
          blob = getClientAudioBlob(key);
          for (let attempt = 0; attempt < 30 && !blob; attempt++) {
            await new Promise((r) => setTimeout(r, 100));
            if (cancelled) return;
            blob = getClientAudioBlob(key);
          }
        } else if (line.audio_url) {
          try {
            blob = await (getCachedBlob(line.audio_url) ?? fetch(line.audio_url).then((r) => r.blob()));
          } catch {
            blob = null;
          }
        }

        if (!blob || cancelled) continue;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        const unregister = registerAudioStop(() => {
          try { audio.pause(); } catch { /* ignore */ }
          URL.revokeObjectURL(url);
        });
        cleanup = () => {
          unregister();
          try { audio.pause(); } catch { /* ignore */ }
          URL.revokeObjectURL(url);
        };

        await new Promise<void>((resolve) => {
          audio.addEventListener('ended', () => resolve(), { once: true });
          audio.addEventListener('error', () => resolve(), { once: true });
          void audio.play().catch(() => resolve());
        });
        cleanup?.();
        cleanup = null;
      }
      if (!cancelled) setSpeaking(false);
    })();

    return () => {
      cancelled = true;
      cleanup?.();
      stopAllAudio();
      setSpeaking(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardIdx]);

  // Mark visited after the playback effect runs at least once.
  useEffect(() => {
    setVisited((prev) => {
      if (prev.has(cardIdx)) return prev;
      const next = new Set(prev);
      next.add(cardIdx);
      return next;
    });
  }, [cardIdx]);

  // ─── Server-side progress persistence ─────────────────────────────────
  const persistProgress = useCallback(
    (idx: number, markComplete: boolean) => {
      if (!sessionId) return;
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current);
      }
      const delay = markComplete ? 0 : PROGRESS_DEBOUNCE_MS;
      debounceRef.current = window.setTimeout(() => {
        postCardProgress(sessionId, {
          phase: 'dialogue_phase',
          card_idx: idx,
          mark_complete: markComplete,
        })
          .then((res) => {
            if (markComplete && res.is_complete) {
              onComplete?.(res);
            }
          })
          .catch((err) => console.warn('postCardProgress failed', err));
        debounceRef.current = null;
      }, delay);
    },
    [sessionId, onComplete],
  );

  // When the summary card becomes visible, mark the session complete.
  useEffect(() => {
    if (!currentCard) return;
    if (currentCard.card_type === 'summary' && !completed) {
      setCompleted(true);
      persistProgress(cardIdx, true);
    } else {
      persistProgress(cardIdx, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardIdx]);

  // ─── Navigation ────────────────────────────────────────────────────────
  const goNext = () => {
    stopAllAudio();
    if (cardIdx < totalCards - 1) setCardIdx(cardIdx + 1);
  };
  const goPrev = () => {
    stopAllAudio();
    if (cardIdx > 0) setCardIdx(cardIdx - 1);
  };

  const onCheckInComplete = (_result: CheckInActivityResult) => {
    // Auto-advance after the activity reports completion.
    goNext();
  };

  // ─── Render ────────────────────────────────────────────────────────────
  if (!currentCard) {
    return <div className="baatcheet-viewer baatcheet-viewer--empty">No dialogue to display.</div>;
  }

  const speakerName =
    currentCard.speaker_name ??
    (currentCard.speaker === 'tutor' ? 'Mr. Verma' : currentCard.speaker === 'peer' ? 'Meera' : null);

  const lineDisplay = currentCard.lines
    .map((l) => materializeText(l.display, personalization))
    .join('\n');

  const visualExplanation = currentCard.visual_explanation;
  const visualPixiCode = visualExplanation?.pixi_code || null;

  return (
    <div className="baatcheet-viewer" data-card-type={currentCard.card_type}>
      <div className="baatcheet-viewer__progress">
        Card {cardIdx + 1} / {totalCards}
      </div>

      {/* Speaker avatar + name (hidden for visual + summary cards if no speaker) */}
      {currentCard.speaker && (
        <div className="baatcheet-viewer__speaker">
          <SpeakerAvatar speaker={currentCard.speaker} speaking={speaking} />
          {speakerName && <div className="baatcheet-viewer__speaker-name">{speakerName}</div>}
        </div>
      )}

      {currentCard.card_type === 'check_in' && currentCard.check_in ? (
        <div className="baatcheet-viewer__check-in">
          {currentCard.title && <h3>{currentCard.title}</h3>}
          <CheckInDispatcher
            checkIn={currentCard.check_in}
            onComplete={onCheckInComplete}
          />
        </div>
      ) : currentCard.card_type === 'visual' ? (
        <div className="baatcheet-viewer__visual">
          {currentCard.title && <h3>{currentCard.title}</h3>}
          {visualPixiCode && visualExplanation ? (
            <VisualExplanationComponent
              visual={visualExplanation}
              autoStart={!visited.has(cardIdx)}
            />
          ) : (
            currentCard.visual_intent && (
              <div className="baatcheet-viewer__line">
                <p className="baatcheet-viewer__line-text">{currentCard.visual_intent}</p>
              </div>
            )
          )}
          {lineDisplay && (
            <div className="baatcheet-viewer__line">{lineDisplay}</div>
          )}
        </div>
      ) : (
        <div className="baatcheet-viewer__line">
          {currentCard.title && <h3 className="baatcheet-viewer__title">{currentCard.title}</h3>}
          {lineDisplay.split('\n').map((line, i) => (
            <p key={i} className="baatcheet-viewer__line-text">{line}</p>
          ))}
        </div>
      )}

      {currentCard.card_type !== 'check_in' && (
        <div className="baatcheet-viewer__nav">
          <button
            type="button"
            className="baatcheet-nav-button"
            onClick={goPrev}
            disabled={cardIdx === 0}
          >
            ← Back
          </button>
          <button
            type="button"
            className="baatcheet-nav-button baatcheet-nav-button--primary"
            onClick={goNext}
            disabled={cardIdx >= totalCards - 1}
          >
            {currentCard.card_type === 'summary' ? 'Done' : 'Next →'}
          </button>
        </div>
      )}
    </div>
  );
}
