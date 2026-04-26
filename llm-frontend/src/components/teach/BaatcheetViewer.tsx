/**
 * BaatcheetViewer — renders a Baatcheet (Mr. Verma + Meera) dialogue.
 *
 * Visual chrome inherits from Explain — the card lives inside a
 * `.app.chalkboard-active` shell provided by ChatSession. This component
 * renders only the per-card body (card-type badge, speaker chip, prose,
 * bottom nav). See docs/feature-development/baatcheet/explain-ux-consistency-audit.md.
 *
 * Owns:
 *   - card index state (current_card_idx)
 *   - audio playback (pre-rendered MP3 OR synthetic-key blob for personalized)
 *   - check-in dispatch (reuses CheckInDispatcher)
 *   - server-side progress posting (debounced) + summary completion mark
 *
 * Exposes (via ref):
 *   - replayCurrent(): re-trigger playback for the current card
 *   - stopAudio(): halt any in-flight playback
 */
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
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
import ConfirmDialog from '../ConfirmDialog';
import VisualExplanationComponent from '../VisualExplanation';

export interface BaatcheetViewerProgress {
  cardIdx: number;
  totalCards: number;
  speaking: boolean;
}

export interface BaatcheetViewerHandle {
  replayCurrent: () => void;
  stopAudio: () => void;
}

interface Props {
  sessionId: string;
  cards: DialogueCard[];
  personalization: Personalization;
  initialCardIdx?: number;
  language?: string;
  onComplete?: (info: CardProgressResponse) => void;
  onProgressChange?: (progress: BaatcheetViewerProgress) => void;
}

const PROGRESS_DEBOUNCE_MS = 500;

function materializeText(text: string, p: Personalization): string {
  const name = (p.student_name || '').trim() || p.fallback_student_name || 'friend';
  return text
    .replaceAll('{student_name}', name)
    .replaceAll('{topic_name}', p.topic_name);
}

function cardTypeBadge(cardType: DialogueCard['card_type']): string | null {
  switch (cardType) {
    case 'dialogue': return 'DIALOGUE';
    case 'visual': return 'VISUAL';
    case 'check_in': return 'CHECK-IN';
    case 'summary': return 'SUMMARY';
    default: return null;
  }
}

const BaatcheetViewer = forwardRef<BaatcheetViewerHandle, Props>(function BaatcheetViewer(
  {
    sessionId,
    cards,
    personalization,
    initialCardIdx = 0,
    language = 'hinglish',
    onComplete,
    onProgressChange,
  },
  ref,
) {
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
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);
  // Bumping this re-triggers the playback effect for the current card.
  const [replayCounter, setReplayCounter] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const debounceRef = useRef<number | null>(null);
  // Set true when the parent calls stopAudio() — the playback loop checks
  // this between lines and breaks out instead of advancing to the next line
  // after stopAllAudio() has paused the current one.
  const cancelPlaybackRef = useRef(false);

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
  // time a card is visited; revisited cards stay silent (PRD §FR-31). A
  // bump to `replayCounter` re-triggers playback even on revisited cards
  // so the top-nav replay button works.
  useEffect(() => {
    if (!currentCard) return;
    const isFirstVisit = !visited.has(cardIdx);
    const isReplay = replayCounter > 0;
    if (!isFirstVisit && !isReplay) return;
    if (currentCard.card_type === 'check_in') {
      // CheckInDispatcher handles its own audio.
      return;
    }

    let cancelled = false;
    let cleanup: (() => void) | null = null;
    cancelPlaybackRef.current = false;
    setSpeaking(true);

    (async () => {
      for (let lineIdx = 0; lineIdx < currentCard.lines.length; lineIdx++) {
        if (cancelled || cancelPlaybackRef.current) break;
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

        if (!blob || cancelled || cancelPlaybackRef.current) continue;
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
          // 'pause' fires when stopAllAudio() pauses this line — without it
          // the loop would hang on stop, never advancing to the cancelled
          // check on the next iteration.
          audio.addEventListener('pause', () => resolve(), { once: true });
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
  }, [cardIdx, replayCounter]);

  // Mark visited after the playback effect runs at least once.
  useEffect(() => {
    setVisited((prev) => {
      if (prev.has(cardIdx)) return prev;
      const next = new Set(prev);
      next.add(cardIdx);
      return next;
    });
  }, [cardIdx]);

  // ─── Imperative handle (replay / stop driven by parent's nav button) ──
  useImperativeHandle(ref, () => ({
    replayCurrent: () => {
      cancelPlaybackRef.current = true;
      stopAllAudio();
      // Bumping replayCounter triggers a fresh playback effect run, which
      // resets cancelPlaybackRef.current back to false on entry.
      setReplayCounter((n) => n + 1);
    },
    stopAudio: () => {
      cancelPlaybackRef.current = true;
      stopAllAudio();
      setSpeaking(false);
    },
  }), []);

  // ─── Progress mirroring (parent renders counter + audio button) ───────
  useEffect(() => {
    onProgressChange?.({ cardIdx, totalCards, speaking });
  }, [cardIdx, totalCards, speaking, onProgressChange]);

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
    cancelPlaybackRef.current = true;
    stopAllAudio();
    if (cardIdx < totalCards - 1) setCardIdx(cardIdx + 1);
  };
  const goPrev = () => {
    cancelPlaybackRef.current = true;
    stopAllAudio();
    if (cardIdx > 0) setCardIdx(cardIdx - 1);
  };
  const performRestart = () => {
    setRestartConfirmOpen(false);
    cancelPlaybackRef.current = true;
    stopAllAudio();
    setVisited(new Set());
    setSpeaking(false);
    setCompleted(false);
    setCardIdx(0);
    // Server sync is handled by the cardIdx-change effect — no explicit
    // persistProgress call needed here.
  };
  const handleRestart = () => setRestartConfirmOpen(true);
  const showRestart =
    cardIdx > 0 && currentCard?.card_type !== 'summary';

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
  const cardBadge = cardTypeBadge(currentCard.card_type);

  return (
    <div
      className="baatcheet-viewer"
      data-card-type={currentCard.card_type}
      // re-key on cardIdx so React replays the slide-fade animation on advance
      key={`baatcheet-card-${cardIdx}`}
    >
      {(cardBadge || (currentCard.speaker && speakerName)) && (
        <div className="baatcheet-card-head">
          {cardBadge && (
            <span className="explanation-card-type">{cardBadge}</span>
          )}
          {currentCard.speaker && speakerName && (
            <div className="baatcheet-speaker-chip" data-speaker={currentCard.speaker}>
              <SpeakerAvatar speaker={currentCard.speaker} speaking={speaking} />
              <span className="baatcheet-speaker-chip__name">{speakerName}</span>
            </div>
          )}
        </div>
      )}

      {currentCard.card_type === 'check_in' && currentCard.check_in ? (
        <div className="baatcheet-viewer__body baatcheet-viewer__check-in">
          {currentCard.title && <h3 className="baatcheet-viewer__title">{currentCard.title}</h3>}
          <CheckInDispatcher
            checkIn={currentCard.check_in}
            onComplete={onCheckInComplete}
          />
        </div>
      ) : currentCard.card_type === 'visual' ? (
        <div className="baatcheet-viewer__body baatcheet-viewer__visual">
          {currentCard.title && <h3 className="baatcheet-viewer__title">{currentCard.title}</h3>}
          {visualPixiCode && visualExplanation ? (
            <VisualExplanationComponent
              visual={visualExplanation}
              autoStart={!visited.has(cardIdx)}
            />
          ) : (
            currentCard.visual_intent && (
              <p className="baatcheet-viewer__line-text">{currentCard.visual_intent}</p>
            )
          )}
          {lineDisplay && lineDisplay.split('\n').map((line, i) => (
            <p key={i} className="baatcheet-viewer__line-text">{line}</p>
          ))}
        </div>
      ) : (
        <div className="baatcheet-viewer__body">
          {currentCard.title && <h3 className="baatcheet-viewer__title">{currentCard.title}</h3>}
          {lineDisplay.split('\n').map((line, i) => (
            <p key={i} className="baatcheet-viewer__line-text">{line}</p>
          ))}
        </div>
      )}

      {currentCard.card_type !== 'check_in' && (
        <div className="explanation-nav">
          <div className="explanation-nav-row">
            <button
              type="button"
              className="explanation-nav-btn secondary"
              onClick={goPrev}
              disabled={cardIdx === 0}
            >
              Back
            </button>
            {showRestart && (
              <button
                type="button"
                className="explanation-nav-btn restart"
                onClick={handleRestart}
                title="Restart from the first card"
                aria-label="Restart from the first card"
              >
                ↻ Restart
              </button>
            )}
            <button
              type="button"
              className="explanation-nav-btn primary"
              onClick={goNext}
              disabled={cardIdx >= totalCards - 1}
            >
              {currentCard.card_type === 'summary' ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      )}

      {/* Restart-only row for check-in cards — Back/Next are gated by the
          activity itself, but a stuck student still needs an escape hatch. */}
      {currentCard.card_type === 'check_in' && cardIdx > 0 && (
        <div className="explanation-nav">
          <div className="explanation-nav-row">
            <button
              type="button"
              className="explanation-nav-btn restart"
              onClick={handleRestart}
              title="Restart from the first card"
              aria-label="Restart from the first card"
            >
              ↻ Restart
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={restartConfirmOpen}
        title="Restart from the beginning?"
        message="You'll go back to the first card. Your progress on this topic stays saved."
        confirmLabel="Restart"
        cancelLabel="Keep going"
        onConfirm={performRestart}
        onCancel={() => setRestartConfirmOpen(false)}
      />
    </div>
  );
});

export default BaatcheetViewer;
