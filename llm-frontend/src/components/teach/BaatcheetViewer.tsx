/**
 * BaatcheetViewer — renders a Baatcheet (Mr. Verma + Meera) dialogue.
 *
 * Visual chrome inherits from Explain — the card lives inside a
 * `.app.chalkboard-active` shell + `.focus-carousel` provided by ChatSession.
 * This component owns the per-card body: the .focus-track-container that
 * mounts every card in the deck side-by-side, plus the bottom nav.
 * See docs/feature-development/baatcheet/explain-ux-consistency-audit.md.
 *
 * Per-line MP3 + typewriter sync: each dialogue line's audio plays in lockstep
 * with TypewriterMarkdown's word-by-word reveal. onBlockTyped awaits the line's
 * Audio('ended'|'error'|'pause') before TW advances to the next line.
 *
 * Owns:
 *   - card index state (current_card_idx)
 *   - per-line audio playback via playDialogueLineAudio (personalized synth or
 *     pre-rendered MP3 — chooses based on card.includes_student_name)
 *   - revealedCards: cards whose typewriter has fully revealed; drives
 *     skipAnimation + visual gating + nav-disable-during-animation
 *   - per-card replay epoch + global restart epoch — both feed into slide keys
 *     to force-remount TypewriterMarkdown subtrees on replay/restart
 *   - check-in dispatch (reuses CheckInDispatcher)
 *   - server-side progress posting (debounced) + summary completion mark
 *
 * Exposes (via ref):
 *   - replayCurrent(): re-trigger reveal+playback for the current card
 *   - stopAudio(): halt in-flight audio; typewriter continues silently
 */
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
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
import TypewriterMarkdown from '../TypewriterMarkdown';

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

function hasAnimatableLines(card: DialogueCard | undefined): boolean {
  if (!card) return false;
  return card.lines.some((l) => l.display.trim().length > 0);
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
  // Set when TypewriterMarkdown.onRevealComplete fires for a card. Drives
  // skipAnimation on revisit, gates VisualExplanation mount (autoStart is
  // captured on mount, so the visual must mount AFTER reveal), and disables
  // bottom nav while a text card is animating.
  const [revealedCards, setRevealedCards] = useState<Set<number>>(() => new Set());
  // Per-card replay counter. Bumping a card's value changes its slide key,
  // which forces React to remount that card's TypewriterMarkdown subtree
  // (TW keeps `started`/`completedRef` in component-internal state — only a
  // key bump truly restarts it).
  const [replayEpochByCard, setReplayEpochByCard] = useState<Map<number, number>>(
    () => new Map(),
  );
  // Bumped by performRestart to force-remount every slide.
  const [restartEpoch, setRestartEpoch] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);
  const debounceRef = useRef<number | null>(null);
  // Set true on stop / navigation / restart. playDialogueLineAudio guards on
  // this at entry — when set, returns immediately. After stop, TW keeps
  // revealing words but each line's audio short-circuits → silent reveal
  // continues. Reset to false when the active card changes (new card starts
  // clean).
  const cancelPlaybackRef = useRef(false);
  // Bumped on cancel/replay/navigation. Captured at the start of each
  // playDialogueLineAudio call so late-arriving blob fetches can be discarded.
  const audioVersionRef = useRef(0);
  // Latest cardIdx, mirrored for the imperative handle so replay/stop don't
  // need to re-create on every card change.
  const cardIdxRef = useRef(cardIdx);
  cardIdxRef.current = cardIdx;
  const cardsRef = useRef(cards);
  cardsRef.current = cards;

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

  // Reset cancel + bump audio version when the active card changes so the new
  // card's typewriter starts clean. Any in-flight playLineAudio for the old
  // card is discarded by the version mismatch check.
  useEffect(() => {
    cancelPlaybackRef.current = false;
    audioVersionRef.current++;
    stopAllAudio();
    setSpeaking(false);
  }, [cardIdx]);

  // Auto-reveal cards with no animatable content (e.g. visual-only cards
  // whose lines are blank) once they become active, so nav doesn't lock and
  // the visual mounts. Also covers the "no lines and no visual" degenerate
  // case — student can still navigate forward.
  useEffect(() => {
    if (!currentCard) return;
    if (currentCard.card_type === 'check_in') return;
    if (hasAnimatableLines(currentCard)) return;
    if (revealedCards.has(cardIdx)) return;
    const t = window.setTimeout(() => {
      setRevealedCards((prev) => {
        if (prev.has(cardIdx)) return prev;
        const next = new Set(prev);
        next.add(cardIdx);
        return next;
      });
    }, 80);
    return () => window.clearTimeout(t);
  }, [cardIdx, currentCard, revealedCards]);

  // ─── Per-line audio playback (TypewriterMarkdown.onBlockTyped target) ──
  // Resolves a blob (personalized synthetic-key OR pre-rendered audio_url),
  // plays it via a fresh Audio element, awaits ended/error/pause. Guards on
  // cancelPlaybackRef + audioVersionRef so stop/navigation aborts cleanly
  // without leaving the typewriter waiting forever.
  const playDialogueLineAudio = useCallback(
    async (card: DialogueCard, lineIdx: number): Promise<void> => {
      if (cancelPlaybackRef.current) return;
      const version = audioVersionRef.current;
      const line = card.lines[lineIdx];
      if (!line) return;

      let blob: Blob | null = null;
      if (card.includes_student_name) {
        const key = personalizedAudioKey(card.card_id, lineIdx);
        blob = getClientAudioBlob(key);
        for (let attempt = 0; attempt < 30 && !blob; attempt++) {
          await new Promise((r) => setTimeout(r, 100));
          if (cancelPlaybackRef.current || audioVersionRef.current !== version) return;
          blob = getClientAudioBlob(key);
        }
      } else if (line.audio_url) {
        try {
          blob = await (
            getCachedBlob(line.audio_url) ?? fetch(line.audio_url).then((r) => r.blob())
          );
        } catch {
          blob = null;
        }
      }

      if (!blob || cancelPlaybackRef.current || audioVersionRef.current !== version) return;

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      const unregister = registerAudioStop(() => {
        try { audio.pause(); } catch { /* ignore */ }
        URL.revokeObjectURL(url);
      });

      setSpeaking(true);
      await new Promise<void>((resolve) => {
        audio.addEventListener('ended', () => resolve(), { once: true });
        audio.addEventListener('error', () => resolve(), { once: true });
        // 'pause' fires when stopAllAudio() pauses this line — without it the
        // promise hangs and the typewriter waits forever.
        audio.addEventListener('pause', () => resolve(), { once: true });
        void audio.play().catch(() => resolve());
      });

      unregister();
      try { audio.pause(); } catch { /* ignore */ }
      URL.revokeObjectURL(url);
    },
    [],
  );

  // ─── Imperative handle (replay / stop driven by parent's nav button) ──
  useImperativeHandle(ref, () => ({
    replayCurrent: () => {
      const idx = cardIdxRef.current;
      const card = cardsRef.current[idx];
      if (!card || card.card_type === 'check_in') return;
      cancelPlaybackRef.current = true;
      stopAllAudio();
      audioVersionRef.current++;
      setSpeaking(false);
      setRevealedCards((prev) => {
        if (!prev.has(idx)) return prev;
        const next = new Set(prev);
        next.delete(idx);
        return next;
      });
      setReplayEpochByCard((prev) => {
        const next = new Map(prev);
        next.set(idx, (prev.get(idx) ?? 0) + 1);
        return next;
      });
      cancelPlaybackRef.current = false;
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
    audioVersionRef.current++;
    setRevealedCards(new Set());
    setReplayEpochByCard(new Map());
    setRestartEpoch((e) => e + 1);
    setSpeaking(false);
    setCompleted(false);
    setCardIdx(0);
    cancelPlaybackRef.current = false;
  };
  const handleRestart = () => setRestartConfirmOpen(true);

  const onCheckInComplete = (_result: CheckInActivityResult) => {
    setRevealedCards((prev) => {
      if (prev.has(cardIdx)) return prev;
      const next = new Set(prev);
      next.add(cardIdx);
      return next;
    });
    goNext();
  };

  // Stable mark-revealed callback per card — TypewriterMarkdown's
  // onRevealComplete fires this once per card.
  const markRevealed = useCallback((idx: number) => {
    setRevealedCards((prev) => {
      if (prev.has(idx)) return prev;
      const next = new Set(prev);
      next.add(idx);
      return next;
    });
    setSpeaking(false);
  }, []);

  if (!currentCard) {
    return <div className="baatcheet-viewer baatcheet-viewer--empty">No dialogue to display.</div>;
  }

  // Disable Back/Restart/Next while the active text card is revealing —
  // matches Explain's pattern. Check-in cards manage their own progression
  // (the activity controls Next), so they bypass this gate.
  const activeCardAnimating =
    currentCard.card_type !== 'check_in' &&
    hasAnimatableLines(currentCard) &&
    !revealedCards.has(cardIdx);

  const showRestart = cardIdx > 0 && currentCard.card_type !== 'summary';

  return (
    <div className="baatcheet-viewer">
      <div className="focus-track-container">
        <div
          className="focus-track"
          style={{
            transform: `translateX(${-cardIdx * 100}%)`,
            transition: 'transform 0.3s ease-out',
          }}
        >
          {cards.map((card, i) => {
            const isActive = i === cardIdx;
            const isRevealed = revealedCards.has(i);
            const replayEpoch = replayEpochByCard.get(i) ?? 0;
            const slideKey = `${card.card_id}-r${restartEpoch}-c${replayEpoch}`;
            const speakerName =
              card.speaker_name ??
              (card.speaker === 'tutor' ? 'Mr. Verma' : card.speaker === 'peer' ? 'Meera' : null);
            const cardBadge = cardTypeBadge(card.card_type);

            // Filter out empty-display lines so TypewriterMarkdown doesn't
            // produce 0-word blocks that flash through. Keep originalIdx so
            // playDialogueLineAudio can resolve the right entry in card.lines
            // (matters for personalized synthetic keys, which use the
            // unfiltered lineIdx as part of the cache key).
            const activeLines = card.lines
              .map((line, originalIdx) => ({ line, originalIdx }))
              .filter(({ line }) => line.display.trim().length > 0);
            const audioLines = activeLines.map(({ line }) => ({
              display: materializeText(line.display, personalization),
              audio: materializeText(line.audio, personalization),
              audio_url: line.audio_url ?? undefined,
            }));
            const lineIdxMap = activeLines.map(({ originalIdx }) => originalIdx);

            const visualExplanation = card.visual_explanation;
            const visualPixiCode = visualExplanation?.pixi_code || null;
            // Visual mounts only on the active card AND only after reveal
            // completes (or immediately if there are no lines to animate).
            // Gate on isActive too so inactive visual cards never instantiate
            // a Pixi iframe — this is what keeps the carousel perf-safe with
            // 25-35 mounted slides.
            const visualReady =
              isActive && (isRevealed || !hasAnimatableLines(card));

            const renderTypewriter = () => audioLines.length > 0 && (
              <div className="focus-tutor-msg">
                <TypewriterMarkdown
                  content=""
                  isActive={isActive}
                  skipAnimation={isRevealed}
                  audioLines={audioLines}
                  onBlockTyped={async (_text, blockIdx) => {
                    const originalIdx = lineIdxMap[blockIdx] ?? blockIdx;
                    return playDialogueLineAudio(card, originalIdx);
                  }}
                  onRevealComplete={() => markRevealed(i)}
                />
              </div>
            );

            return (
              <div
                key={slideKey}
                className="focus-slide baatcheet-slide"
                data-card-type={card.card_type}
                aria-hidden={!isActive}
              >
                {(cardBadge || (card.speaker && speakerName)) && (
                  <div className="baatcheet-card-head">
                    {cardBadge && (
                      <span className="explanation-card-type">{cardBadge}</span>
                    )}
                    {card.speaker && speakerName && (
                      <div className="baatcheet-speaker-chip" data-speaker={card.speaker}>
                        <SpeakerAvatar
                          speaker={card.speaker}
                          speaking={isActive && speaking}
                        />
                        <span className="baatcheet-speaker-chip__name">{speakerName}</span>
                      </div>
                    )}
                  </div>
                )}

                {card.card_type === 'check_in' && card.check_in ? (
                  <div className="baatcheet-viewer__body baatcheet-viewer__check-in">
                    {card.title && <h3 className="baatcheet-viewer__title">{card.title}</h3>}
                    {isActive && (
                      <CheckInDispatcher
                        checkIn={card.check_in}
                        onComplete={onCheckInComplete}
                      />
                    )}
                  </div>
                ) : card.card_type === 'visual' ? (
                  <div className="baatcheet-viewer__body baatcheet-viewer__visual">
                    {card.title && <h3 className="baatcheet-viewer__title">{card.title}</h3>}
                    {visualReady && visualPixiCode && visualExplanation ? (
                      <VisualExplanationComponent
                        visual={visualExplanation}
                        autoStart={true}
                      />
                    ) : (
                      visualReady && !visualPixiCode && card.visual_intent && (
                        <p className="baatcheet-viewer__line-text">{card.visual_intent}</p>
                      )
                    )}
                    {renderTypewriter()}
                  </div>
                ) : (
                  <div className="baatcheet-viewer__body">
                    {card.title && <h3 className="baatcheet-viewer__title">{card.title}</h3>}
                    {renderTypewriter()}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {currentCard.card_type !== 'check_in' && (
        <div className="explanation-nav">
          <div className="explanation-nav-row">
            <button
              type="button"
              className="explanation-nav-btn secondary"
              onClick={goPrev}
              disabled={cardIdx === 0 || activeCardAnimating}
            >
              Back
            </button>
            {showRestart && (
              <button
                type="button"
                className="explanation-nav-btn restart"
                onClick={handleRestart}
                disabled={activeCardAnimating}
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
              disabled={cardIdx >= totalCards - 1 || activeCardAnimating}
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
