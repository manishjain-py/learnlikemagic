import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useParams, useLocation, useOutletContext } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { debugLog } from '../debugLog';
import {
  submitStep,
  getSummary,
  getModelConfig,
  getSessionReplay,
  transcribeAudio,
  synthesizeSpeech,
  submitFeedback,
  cardAction,
  simplifyCard,
  TutorWebSocket,
  Turn,
  ExplanationCard,
  CardPhaseDTO,
  SummaryResponse,
  VisualExplanation as VisualExplanationType,
  QuestionFormat,
  CheckInActivity,
  CheckInEventDTO,
  DialogueCard,
  Personalization,
} from '../api';
import BaatcheetViewer from '../components/teach/BaatcheetViewer';
import { useStudentProfile } from '../hooks/useStudentProfile';
import { useAuth } from '../contexts/AuthContext';
import DevToolsDrawer from '../features/devtools/components/DevToolsDrawer';
import VisualExplanationComponent from '../components/VisualExplanation';
import InteractiveQuestion from '../components/InteractiveQuestion';
import CheckInDispatcher, { CheckInActivityResult } from '../components/CheckInDispatcher';
import TypewriterMarkdown from '../components/TypewriterMarkdown';
import { registerAudioStop, stopAllAudio, prefetchAudio as checkInPrefetchAudio, getCachedBlob } from '../hooks/audioController';
import '../App.css';

interface Message {
  role: 'teacher' | 'student';
  content: string;
  audioText?: string | null;
  hints?: string[];
  visualExplanation?: VisualExplanationType | null;
  questionFormat?: QuestionFormat | null;
}

interface Slide {
  id: string;
  type: 'explanation' | 'message' | 'check_in';
  content: string;
  title?: string;
  cardType?: string;
  visual?: string | null;
  visualExplanation?: VisualExplanationType | null;
  questionFormat?: QuestionFormat | null;
  studentResponse?: string | null;
  audioText?: string | null;
  audioUrl?: string;  // Pre-computed S3 URL for the slide-level audio (check-in instruction)
  audioLines?: { display: string; audio: string; audio_url?: string }[];  // Per-line audio from LLM
  checkIn?: CheckInActivity | null;
  simplifications?: ExplanationCard['simplifications'];
}

// ─── Global audio element + unlock ──────────────────────────────────
// Module-scope so it survives route changes. The "Teach Me" tap on
// ModeSelection unlocks the element before ChatSession even mounts.
let _globalAudio: HTMLAudioElement | null = null;
let _audioUnlocked = false;
const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';

function getGlobalAudio(): HTMLAudioElement {
  if (!_globalAudio) _globalAudio = new Audio();
  return _globalAudio;
}

function _unlockAudio() {
  if (_audioUnlocked) return;
  const audio = getGlobalAudio();
  audio.src = SILENT_WAV;
  audio.volume = 0;
  const p = audio.play();
  if (p) p.then(() => {
    audio.pause();
    audio.volume = 1;
    audio.currentTime = 0;
    _audioUnlocked = true;
  }).catch(() => {});
}

// Register unlock on first load — any tap anywhere in the app unlocks audio
document.addEventListener('click', _unlockAudio);
document.addEventListener('touchstart', _unlockAudio);
document.addEventListener('touchend', _unlockAudio);

export default function ChatSession() {
  const navigate = useNavigate();
  const params = useParams<{
    sessionId: string;
    subject?: string;
    chapter?: string;
    topic?: string;
  }>();
  const sessionId = params.sessionId;
  const location = useLocation();
  const { grade, board, studentId } = useStudentProfile();
  const { user } = useAuth();
  const audioLang = user?.audio_language_preference || 'en';

  const locState = location.state as {
    firstTurn?: Turn;
    mode?: string;
    topicKey?: string;
    conversationHistory?: Array<{ role: string; content: string }>;
    currentStep?: number;
  } | null;

  const isRefresher = locState?.topicKey === 'get-ready';

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [totalSteps, setTotalSteps] = useState(0);
  const [mastery, setMastery] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [devToolsOpen, setDevToolsOpen] = useState(false);
  const [modelLabel, setModelLabel] = useState('');
  const [sessionMode, setSessionMode] = useState<'teach_me' | 'clarify_doubts'>(
    (locState?.mode as any) || 'teach_me',
  );
  const [coverage, setCoverage] = useState(0);
  const [conceptsDiscussed, setConceptsDiscussed] = useState<string[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [playingSlideId, setPlayingSlideId] = useState<string | null>(null);

  // Card phase state (pre-computed explanations)
  const [sessionPhase, setSessionPhase] = useState<'card_phase' | 'dialogue_phase' | 'interactive'>('interactive');
  const [explanationCards, setExplanationCards] = useState<ExplanationCard[]>([]);
  // Baatcheet (dialogue phase) state — populated from firstTurn or replay.
  const [dialogueCards, setDialogueCards] = useState<DialogueCard[] | null>(null);
  const [dialoguePersonalization, setDialoguePersonalization] = useState<Personalization | null>(null);
  const [dialogueInitialIdx, setDialogueInitialIdx] = useState(0);
  const [cardPhaseState, setCardPhaseState] = useState<CardPhaseDTO | null>(null);
  const [cardActionLoading, setCardActionLoading] = useState(false);
  const [simplifyLoading, setSimplifyLoading] = useState(false);
  const [simplifyJustAdded, setSimplifyJustAdded] = useState(false);
  const [preloadAnimateCards, setPreloadAnimateCards] = useState<Set<number>>(new Set());
  const [variantsShown, setVariantsShown] = useState(1);

  // Teach Me completion screen state (shown after card phase ends — summary + Practice CTA)
  const [teachMeComplete, setTeachMeComplete] = useState(false);
  const [teachMeCompletionMessage, setTeachMeCompletionMessage] = useState<string | null>(null);
  const [teachMeConceptsCovered, setTeachMeConceptsCovered] = useState<string[]>([]);
  const [teachMeGuidelineId, setTeachMeGuidelineId] = useState<string | null>(null);

  // Typewriter: track which slide indices have been fully revealed
  const [revealedSlides, setRevealedSlides] = useState<Set<number>>(new Set());
  const [typewriterSkip, setTypewriterSkip] = useState<Set<number>>(new Set());
  // Widget reveal sequence: a slide is "fullyReplayed" once the guided tour
  // (scroll to ASCII box → auto-expand Pixi → play narration) has finished.
  // In-memory only — resets on refresh. Revisits within the same session
  // render widgets with the collapsed "See it" button instead of auto-expanded.
  const [fullyReplayed, setFullyReplayed] = useState<Set<number>>(new Set());
  const widgetSequenceRef = useRef<{ slideIdx: number; cancelled: boolean } | null>(null);
  // Check-in gate + struggle tracking — keyed by stable card_id, not mutable slide index
  const [completedCheckIns, setCompletedCheckIns] = useState<Set<string>>(new Set());
  const [checkInStruggles, setCheckInStruggles] = useState<Map<string, CheckInActivityResult>>(new Map());

  // Annotate cards with 0-based source_card_idx if not already present
  const annotateCards = (cards: ExplanationCard[]): ExplanationCard[] =>
    cards.map((c, i) => ({ ...c, source_card_idx: c.source_card_idx ?? i }));

  // Streaming state
  const [streamingText, setStreamingText] = useState('');
  const wsRef = useRef<TutorWebSocket | null>(null);
  const streamResolveRef = useRef<(() => void) | null>(null);

  // Feedback modal state
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState('');
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackSuccess, setFeedbackSuccess] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [feedbackCount, setFeedbackCount] = useState(0);
  const [isFeedbackRecording, setIsFeedbackRecording] = useState(false);
  const feedbackRecorderRef = useRef<MediaRecorder | null>(null);
  const feedbackChunksRef = useRef<Blob[]>([]);
  const [isFeedbackTranscribing, setIsFeedbackTranscribing] = useState(false);
  const isSpeaking = playingSlideId !== null;
  const [currentSlideIdx, setCurrentSlideIdx] = useState(0);
  const focusTrackRef = useRef<HTMLDivElement>(null);
  const prevSlidesLen = useRef(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const initializedRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioCacheRef = useRef<Map<string, Promise<Blob>>>(new Map());
  const audioPlayVersion = useRef(0);

  // URL params from nested learn routes (preferred) — already decoded by React Router
  const subject = params.subject || '';
  const chapter = params.chapter || '';
  const topic = params.topic || '';

  // Derive unified carousel slides — continuous sequence of explanation cards + messages
  const carouselSlides = useMemo(() => {
    const slides: Slide[] = [];

    // Explanation cards (including welcome as first card)
    if (explanationCards.length > 0) {
      explanationCards.forEach((card, i) => {
        if (card.card_type === 'check_in' && card.check_in) {
          slides.push({
            id: card.card_id || `card-${i}`,
            type: 'check_in',
            content: card.check_in.instruction,
            title: card.title,
            cardType: 'check_in',
            checkIn: card.check_in,
            audioText: card.check_in.audio_text,
            audioUrl: card.check_in.audio_text_url,
          });
        } else {
          slides.push({
            id: card.card_id || `card-${i}`,
            type: 'explanation',
            content: card.content,
            title: card.title,
            cardType: card.card_type,
            visual: card.visual,
            visualExplanation: card.visual_explanation || null,
            audioText: card.audio_text || card.content,
            audioLines: card.lines,
            simplifications: card.simplifications || [],
          });
        }
      });
    }

    // 2. In interactive phase, append message slides after explanation cards
    if (sessionPhase === 'interactive') {
      for (let i = 0; i < messages.length; i++) {
        if (messages[i].role === 'teacher') {
          // Skip the initial welcome message when explanation cards exist —
          // the user saw explanation cards instead, so this message is redundant
          if (explanationCards.length > 0 && i === 0) continue;

          const next = (i + 1 < messages.length && messages[i + 1].role === 'student')
            ? messages[i + 1] : null;
          slides.push({
            id: `msg-${i}`,
            type: 'message',
            content: messages[i].content,
            visualExplanation: messages[i].visualExplanation,
            questionFormat: messages[i].questionFormat,
            studentResponse: next?.content || null,
            audioText: messages[i].audioText,
          });
        }
      }

      // Append provisional streaming slide
      if (streamingText) {
        slides.push({
          id: 'streaming',
          type: 'message',
          content: streamingText,
        });
      }
    }

    return slides;
  }, [sessionPhase, explanationCards, messages, streamingText]);

  // Active structured question: the last slide's questionFormat if it hasn't been answered
  const activeQuestionFormat = useMemo(() => {
    if (sessionPhase !== 'interactive' || loading) return null;
    const lastSlide = carouselSlides[carouselSlides.length - 1];
    if (!lastSlide || lastSlide.type !== 'message' || lastSlide.studentResponse) return null;
    return lastSlide.questionFormat || null;
  }, [carouselSlides, sessionPhase, loading]);

  // Auto-advance carousel when new slides appear
  useEffect(() => {
    if (isComplete) return;
    const prev = prevSlidesLen.current;
    prevSlidesLen.current = carouselSlides.length;
    if (carouselSlides.length > prev && prev > 0) {
      // Only auto-advance if user was on the last slide
      if (currentSlideIdx === prev - 1) {
        const newIdx = carouselSlides.length - 1;
        setCurrentSlideIdx(newIdx);
        // Auto-play TTS for new slide (skip streaming slide)
        const newSlide = carouselSlides[newIdx];
        if (newSlide && newSlide.id !== 'streaming' && newSlide.type !== 'explanation') {
          playTeacherAudio(newSlide.audioText || newSlide.content, newSlide.id, newSlide.audioUrl);
        }
      }
    }
  }, [carouselSlides.length]);

  // Clamp slide index to valid range — prevents blank screen on out-of-bounds.
  // During card_phase, currentSlideIdx === carouselSlides.length is the valid
  // "past last card" state that shows the "Start practice" nav, so don't clamp it.
  useEffect(() => {
    if (carouselSlides.length > 0 && currentSlideIdx >= carouselSlides.length) {
      if (sessionPhase === 'card_phase' && currentSlideIdx === carouselSlides.length) return;
      setCurrentSlideIdx(carouselSlides.length - 1);
    }
  }, [currentSlideIdx, carouselSlides.length, sessionPhase]);

  // Auto-play audio when navigating explanation cards (Back/Next or swipe)
  const prevSlideIdx = useRef(0);
  useEffect(() => {
    if (prevSlideIdx.current === currentSlideIdx) return;
    prevSlideIdx.current = currentSlideIdx;
    if (sessionPhase !== 'card_phase') return;
    // Stop prior card's audio and cancel any in-flight TTS fetches before
    // (maybe) starting the new card's audio. stopAllAudio() silences every
    // registered track (teacher audio, per-line audio, check-in hook audio);
    // stopAudio() also bumps audioPlayVersion so late-arriving prefetches in
    // playLineAudio/playTeacherAudio discard themselves.
    stopAllAudio();
    stopAudio();
    // Cancel any in-flight widget reveal sequence — student has navigated
    // away from the slide that was running it.
    if (widgetSequenceRef.current) {
      widgetSequenceRef.current.cancelled = true;
      widgetSequenceRef.current = null;
    }
    const slide = carouselSlides[currentSlideIdx];
    // Auto-play for message and check_in slides; explanation slides use per-line typewriter audio
    if (slide && (slide.type === 'message' || slide.type === 'check_in')) {
      playTeacherAudio(slide.audioText || slide.content, slide.id, slide.audioUrl);
    }
  }, [currentSlideIdx, sessionPhase, carouselSlides]);

  // Pre-fetch all TTS audio for the current explanation card in batches.
  // Fires when the slide changes so audio is cached before the typewriter
  // reaches each line. Batches of 3 with 300ms gaps avoid flooding the
  // TTS endpoint. Also pre-fetches the next slide's first few lines.
  useEffect(() => {
    if (sessionPhase !== 'card_phase') return;
    const slide = carouselSlides[currentSlideIdx];
    if (!slide?.audioLines?.length) return;

    const BATCH_SIZE = 3;
    const BATCH_DELAY = 300;
    const timers: ReturnType<typeof setTimeout>[] = [];

    slide.audioLines.forEach((line, i) => {
      if (!line.audio?.trim()) return;
      const batchIdx = Math.floor(i / BATCH_SIZE);
      if (batchIdx === 0) {
        prefetchAudio(line.audio, line.audio_url);
      } else {
        timers.push(setTimeout(() => prefetchAudio(line.audio, line.audio_url), batchIdx * BATCH_DELAY));
      }
    });

    // Prefetch the visual-explanation narration so it's cached by the time
    // the widget reveal sequence reaches the Pixi step (typewriter runs first,
    // so we can queue this after the main line batches).
    const narration = slide.visualExplanation?.narration?.trim();
    if (narration) {
      const narrationDelay = Math.ceil(slide.audioLines.length / BATCH_SIZE) * BATCH_DELAY + 200;
      timers.push(setTimeout(() => prefetchAudio(narration), narrationDelay));
    }

    // Look-ahead: also prefetch next slide's first few lines for smoother transition
    const nextSlide = carouselSlides[currentSlideIdx + 1];
    if (nextSlide?.audioLines?.length) {
      const nextDelay = Math.ceil(slide.audioLines.length / BATCH_SIZE) * BATCH_DELAY + 500;
      nextSlide.audioLines.slice(0, BATCH_SIZE).forEach((line, i) => {
        if (!line.audio?.trim()) return;
        timers.push(setTimeout(() => prefetchAudio(line.audio, line.audio_url), nextDelay + i * 100));
      });
    }

    // Look-ahead for check-in slides: explanation lines get "typewriter cover"
    // for their fetch latency, but a check-in's instruction audio plays the
    // instant the slide arrives — with no cover time, it'd be stuck on the
    // ~800ms S3 round-trip. Warm the global blob cache now so by the time the
    // student advances to the check-in, the blobs are already in hand.
    if (nextSlide?.checkIn) {
      const nextDelay = Math.ceil(slide.audioLines.length / BATCH_SIZE) * BATCH_DELAY + 500;
      timers.push(setTimeout(() => {
        checkInPrefetchAudio(nextSlide.checkIn?.audio_text_url);
        checkInPrefetchAudio(nextSlide.checkIn?.hint_audio_url);
        checkInPrefetchAudio(nextSlide.checkIn?.success_audio_url);
        checkInPrefetchAudio(nextSlide.checkIn?.reveal_audio_url);
      }, nextDelay));
    }

    return () => timers.forEach(clearTimeout);
  }, [currentSlideIdx, sessionPhase, carouselSlides]);

  useEffect(() => {
    getModelConfig()
      .then((config) => setModelLabel(config.tutor?.description || config.tutor?.model_id || ''))
      .catch(() => setModelLabel(''));
  }, []);

  // Initialize session from location state or replay API
  useEffect(() => {
    if (initializedRef.current || !sessionId) return;
    initializedRef.current = true;

    if (locState?.firstTurn) {
      // Fresh session from ModeSelectPage
      // Baatcheet (dialogue) phase short-circuits the explanation/card path.
      if (
        locState.firstTurn.session_phase === 'dialogue_phase' &&
        locState.firstTurn.dialogue_cards
      ) {
        setSessionPhase('dialogue_phase');
        setDialogueCards(locState.firstTurn.dialogue_cards);
        setDialoguePersonalization(locState.firstTurn.personalization || null);
        setDialogueInitialIdx(
          locState.firstTurn.dialogue_phase_state?.current_card_idx ?? 0,
        );
      }
      // Check for card phase (pre-computed explanations)
      else if (locState.firstTurn.session_phase === 'card_phase' && locState.firstTurn.explanation_cards) {
        setSessionPhase('card_phase');
        const cards = annotateCards(locState.firstTurn.explanation_cards);
        setExplanationCards(cards);
        setCurrentSlideIdx(0);
        setCardPhaseState(locState.firstTurn.card_phase_state || null);
        setVariantsShown(1);
        // Pre-reveal cards with saved simplifications (returning student):
        // original content + all-but-last simplification shown fully,
        // last simplification gets typewriter animation
        const preRevealed = new Set<number>();
        cards.forEach((c: any, idx: number) => { if (c.simplifications?.length) preRevealed.add(idx); });
        if (preRevealed.size > 0) {
          setRevealedSlides(prev => new Set([...prev, ...preRevealed]));
          setFullyReplayed(prev => new Set([...prev, ...preRevealed]));
          setPreloadAnimateCards(preRevealed);
        }
      }

      setMessages([{
        role: 'teacher',
        content: locState.firstTurn.message,
        audioText: locState.firstTurn.audio_text,
        hints: locState.firstTurn.hints,
        visualExplanation: locState.firstTurn.visual_explanation,
      }]);
      setStepIdx(locState.firstTurn.step_idx);
      if ((locState.firstTurn as any).total_steps) setTotalSteps((locState.firstTurn as any).total_steps);
      setMastery(locState.firstTurn.mastery_score);

      // Auto-play TTS for first slide
      if (locState.firstTurn.session_phase === 'card_phase') {
        // Welcome is the first card — typewriter handles per-line audio
        prevSlidesLen.current = (locState.firstTurn.explanation_cards?.length || 0);
      } else {
        prevSlidesLen.current = 1;
        playTeacherAudio(locState.firstTurn.audio_text || locState.firstTurn.message, 'msg-0');
      }
    } else if (locState?.conversationHistory) {
      // Resumed session
      setMessages(
        locState.conversationHistory.map((m: any) => ({
          role: m.role === 'student' ? 'student' as const : 'teacher' as const,
          content: m.content,
          audioText: m.audio_text || null,
        })),
      );
      if (locState.currentStep) setStepIdx(locState.currentStep);
    } else {
      // Deep link / page refresh — load from replay API
      setReplayLoading(true);
      getSessionReplay(sessionId)
        .then((state) => {
          const history = state.full_conversation_log || [];
          setMessages(
            history.map((m: any) => ({
              role: m.role === 'student' ? 'student' as const : 'teacher' as const,
              content: m.content,
              audioText: m.audio_text || null,
            })),
          );
          // Hydrate step — backend field is current_step
          if (state.current_step != null) setStepIdx(state.current_step);
          if (state.mode) setSessionMode(state.mode);
          if (state.concepts_discussed) setConceptsDiscussed(state.concepts_discussed);

          // Hydrate dialogue phase (Baatcheet) on resume / deep-link.
          if (state._replay_dialogue_cards && state.dialogue_phase) {
            setDialogueCards(state._replay_dialogue_cards);
            setDialoguePersonalization(
              state._replay_dialogue_personalization || {
                student_name: null,
                fallback_student_name: 'friend',
                topic_name: '',
              },
            );
            const initialIdx = state.dialogue_phase.current_card_idx ?? 0;
            setDialogueInitialIdx(initialIdx);
            if (state.dialogue_phase.active) {
              setSessionPhase('dialogue_phase');
            }
            // else: completed dialogue — viewer still renders for review
            // when the user lands on this URL.
          }

          // Hydrate card phase — active or completed
          if (state._replay_explanation_cards) {
            const replayCards = annotateCards(state._replay_explanation_cards);
            setExplanationCards(replayCards);
            // Pre-reveal cards with saved simplifications (returning student / resume)
            const preRevealed = new Set<number>();
            replayCards.forEach((c: any, idx: number) => { if (c.simplifications?.length) preRevealed.add(idx); });
            if (preRevealed.size > 0) {
              setRevealedSlides(prev => new Set([...prev, ...preRevealed]));
              setFullyReplayed(prev => new Set([...prev, ...preRevealed]));
              setPreloadAnimateCards(preRevealed);
            }

            if (state.card_phase?.active) {
              // Card phase still in progress — restore card navigation state.
              // localStorage is the truth source for Explain: forward/back nav
              // writes there on every advance. Server-side `current_card_idx`
              // is only updated by the WS card_navigate handler that no
              // frontend caller invokes today, so the server value is always
              // the initial 0. Until Explain nav is wired to /card-progress
              // (see TODO in record_card_progress), prefer localStorage.
              let slideIdx = 0;
              const savedPos = localStorage.getItem(`slide-pos-${sessionId}`);
              if (savedPos !== null) {
                const parsed = parseInt(savedPos, 10);
                if (!isNaN(parsed)) slideIdx = parsed;
              } else if (state.card_phase.current_card_idx != null) {
                slideIdx = state.card_phase.current_card_idx;
              }
              setSessionPhase('card_phase');
              setCurrentSlideIdx(slideIdx);
              prevSlidesLen.current = state._replay_explanation_cards.length;
              setCardPhaseState({
                current_variant_key: state.card_phase.current_variant_key,
                current_card_idx: slideIdx,
                total_cards: state.card_phase.total_cards,
                available_variants: state.card_phase.available_variant_keys?.length || 0,
              });
              setVariantsShown(state.card_phase.variants_shown?.length || 1);
            }
            // else: card phase completed — cards loaded for history but sessionPhase stays 'interactive'
          }

          // Hydrate completion using backend is_complete (single source of truth).
          const completed = state.is_complete
            ?? (state.clarify_complete
                || (state.topic && state.current_step > (state.topic?.study_plan?.steps?.length ?? Infinity)));
          if (completed) {
            setIsComplete(true);
          }
        })
        .catch((err) => {
          console.error('Failed to load session:', err);
        })
        .finally(() => setReplayLoading(false));
    }

    // Clear location state so refresh doesn't re-trigger
    navigate(location.pathname, { replace: true, state: null });
  }, [sessionId]);

  // Connect WebSocket for streaming
  useEffect(() => {
    if (!sessionId) return;

    const ws = new TutorWebSocket(sessionId, {
      onToken: (text) => {
        setStreamingText((prev) => prev + text);
      },
      onAssistant: (message, audioText, visualExplanation, questionFormat) => {
        // Finalize: replace streaming text with the complete message
        setStreamingText('');
        setMessages((prev) => [
          ...prev,
          {
            role: 'teacher',
            content: message,
            audioText: audioText,
            visualExplanation: visualExplanation,
            questionFormat: questionFormat,
          },
        ]);
        setLoading(false);

        // Auto-play TTS is handled by the auto-advance effect

        // Resolve the pending send promise
        streamResolveRef.current?.();
        streamResolveRef.current = null;
      },
      onVisualUpdate: (visualExplanation) => {
        // Attach visual to the last teacher message (sent separately for latency)
        setMessages((prev) => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === 'teacher') {
              updated[i] = { ...updated[i], visualExplanation: visualExplanation };
              break;
            }
          }
          return updated;
        });
      },
      onStateUpdate: (state) => {
        if (state.current_step != null) setStepIdx(state.current_step);
        if (state.total_steps != null) setTotalSteps(state.total_steps);
        if (state.mastery_estimates) {
          const values = Object.values(state.mastery_estimates);
          if (values.length > 0) {
            setMastery(values.reduce((a, b) => a + b, 0) / values.length);
          }
        }
        if (state.concepts_discussed) setConceptsDiscussed(state.concepts_discussed);
        if (state.is_complete) {
          setIsComplete(true);
          if (sessionMode !== 'clarify_doubts') {
            getSummary(sessionId).then(setSummary).catch(() => {});
          }
        }
      },
      onTyping: () => {
        // Typing indicator is handled by the loading state
      },
      onError: (error) => {
        console.error('WebSocket error:', error);
        setLoading(false);
        setStreamingText('');
        streamResolveRef.current?.();
        streamResolveRef.current = null;
      },
      onClose: () => {
        // Connection closed — future sends will fall back to REST
      },
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
      wsRef.current = null;
      audioCacheRef.current.clear();
    };
  }, [sessionId, sessionMode]);

  // Core message-sending logic, used by both handleSubmit and structured question submit
  const sendMessage = async (text: string) => {
    if (!text.trim() || !sessionId || loading) return;
    const userMessage = text.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'student', content: userMessage }]);
    setLoading(true);

    if (wsRef.current?.isConnected) {
      wsRef.current.sendChat(userMessage);
      await new Promise<void>((resolve) => {
        streamResolveRef.current = resolve;
      });
      return;
    }

    try {
      const response = await submitStep(sessionId, userMessage);
      setMessages((prev) => [
        ...prev,
        {
          role: 'teacher',
          content: response.next_turn.message,
          audioText: response.next_turn.audio_text,
          hints: response.next_turn.hints,
          visualExplanation: response.next_turn.visual_explanation,
          questionFormat: response.next_turn.question_format,
        },
      ]);
      setStepIdx(response.next_turn.step_idx);
      setMastery(response.next_turn.mastery_score);
      if (response.next_turn.concepts_discussed) {
        setConceptsDiscussed(response.next_turn.concepts_discussed);
      }
      if (response.next_turn.is_complete) {
        setIsComplete(true);
        if (sessionMode !== 'clarify_doubts') {
          const summaryData = await getSummary(sessionId);
          setSummary(summaryData);
        }
      }
    } catch (err) {
      console.error('REST submit failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !sessionId || loading) return;
    await sendMessage(input);
  };

  const handleBack = () => {
    if (subject && chapter && topic) {
      navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}`);
    } else {
      navigate('/learn');
    }
  };

  const toggleRecording = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredTypes = ['audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t));
      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const activeMime = mediaRecorder.mimeType || 'audio/webm';

      audioChunksRef.current = [];
      const baseInput = input;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        mediaRecorderRef.current = null;

        const audioBlob = new Blob(audioChunksRef.current, { type: activeMime });
        if (audioBlob.size === 0) return;

        setIsTranscribing(true);
        try {
          const text = await transcribeAudio(audioBlob);
          if (text) {
            const spacer = baseInput && !baseInput.endsWith(' ') ? ' ' : '';
            setInput(`${baseInput}${spacer}${text}`);
          }
        } catch (err) {
          console.error('Transcription failed:', err);
        } finally {
          setIsTranscribing(false);
        }
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Microphone access denied:', err);
    }
  };

  // Use the module-scope audio element (unlocked by any tap in the app)
  const getOrCreateAudio = (): HTMLAudioElement => {
    const audio = getGlobalAudio();
    audioRef.current = audio;
    return audio;
  };

  const playTeacherAudio = async (text: string, slideId?: string, audioUrl?: string) => {
    // Silence any other track (check-in hook, prior teacher audio) before starting.
    stopAllAudio();
    const version = ++audioPlayVersion.current;
    try {
      const audio = getOrCreateAudio();
      audio.pause();
      if (audio.src && audio.src.startsWith('blob:')) {
        URL.revokeObjectURL(audio.src);
      }

      // Prefer pre-computed S3 MP3 when available; check shared blob cache
      // first (warmed by check-in look-ahead prefetch); then live fetch; then
      // live TTS fallback.
      let audioBlob: Blob;
      if (audioUrl) {
        const cached = getCachedBlob(audioUrl);
        try {
          if (cached) {
            audioBlob = await cached;
          } else {
            const res = await fetch(audioUrl);
            if (!res.ok) throw new Error(`S3 ${res.status}`);
            audioBlob = await res.blob();
          }
        } catch {
          audioBlob = await synthesizeSpeech(text, audioLang);
        }
      } else {
        audioBlob = await synthesizeSpeech(text, audioLang);
      }
      // Discard if a newer play request was made while we were fetching
      if (audioPlayVersion.current !== version) return;
      const url = URL.createObjectURL(audioBlob);
      audio.src = url;
      // Register for global stop so another playback (or option click) silences us.
      const unregister = registerAudioStop(stopAudio);
      audio.onended = () => {
        setPlayingSlideId(null);
        URL.revokeObjectURL(url);
        unregister();
      };
      audio.onerror = () => {
        setPlayingSlideId(null);
        URL.revokeObjectURL(url);
        unregister();
      };
      await audio.play();
      setPlayingSlideId(slideId ?? null);
    } catch (err) {
      console.error('TTS playback failed:', err);
      setPlayingSlideId(null);
    }
  };

  const stopAudio = () => {
    audioPlayVersion.current++; // Cancel any in-flight fetches
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      if (audio.src && audio.src.startsWith('blob:')) {
        URL.revokeObjectURL(audio.src);
      }
      audio.src = '';
    }
    setPlayingSlideId(null);
  };

  const stopAudioWithFade = (): Promise<void> => {
    return new Promise((resolve) => {
      const audio = audioRef.current;
      if (!audio || audio.paused) { setPlayingSlideId(null); resolve(); return; }
      const startVol = audio.volume;
      let step = 0;
      const steps = 6;
      const fadeInterval = setInterval(() => {
        step++;
        audio.volume = Math.max(0, startVol * (1 - step / steps));
        if (step >= steps) {
          clearInterval(fadeInterval);
          audio.pause();
          audio.volume = 1;
          if (audio.src && audio.src.startsWith('blob:')) URL.revokeObjectURL(audio.src);
          audio.src = '';
          setPlayingSlideId(null);
          resolve();
        }
      }, 25);
    });
  };

  const prefetchAudio = (text: string, audioUrl?: string): Promise<Blob> => {
    const key = audioUrl || text;
    const short = text.slice(0, 35);
    if (audioCacheRef.current.has(key)) {
      debugLog(`[AUDIO] prefetch HIT "${short}…" (cache size=${audioCacheRef.current.size})`);
      return audioCacheRef.current.get(key)!;
    }
    // Cap cache at 30 entries to limit memory on mobile devices
    if (audioCacheRef.current.size >= 30) {
      const oldest = audioCacheRef.current.keys().next().value;
      if (oldest !== undefined) audioCacheRef.current.delete(oldest);
    }
    const fetchStart = Date.now();
    let promise: Promise<Blob>;
    if (audioUrl) {
      // Pre-computed audio on S3 — fast CDN download
      debugLog(`[AUDIO] prefetch S3 "${short}…" — ${audioUrl.slice(-40)} (cache size=${audioCacheRef.current.size})`);
      promise = fetch(audioUrl)
        .then(res => {
          if (!res.ok) throw new Error(`S3 fetch ${res.status}`);
          return res.blob();
        })
        .then(blob => {
          debugLog(`[AUDIO] prefetch S3 OK "${short}…" — ${blob.size} bytes in ${Date.now() - fetchStart}ms`);
          return blob;
        })
        .catch(err => {
          debugLog(`[AUDIO] prefetch S3 FAIL "${short}…" — ${err.message}, falling back to TTS`);
          audioCacheRef.current.delete(key);
          // Fall back to real-time TTS
          return synthesizeSpeech(text, audioLang);
        });
    } else {
      // No pre-computed audio — use real-time TTS
      debugLog(`[AUDIO] prefetch TTS "${short}…" — fetching (cache size=${audioCacheRef.current.size})`);
      promise = synthesizeSpeech(text, audioLang)
        .then(blob => {
          debugLog(`[AUDIO] prefetch TTS OK "${short}…" — ${blob.size} bytes in ${Date.now() - fetchStart}ms`);
          return blob;
        })
        .catch(err => {
          debugLog(`[AUDIO] prefetch TTS FAIL "${short}…" — ${err.message} after ${Date.now() - fetchStart}ms`);
          audioCacheRef.current.delete(key);
          throw err;
        });
    }
    audioCacheRef.current.set(key, promise);
    return promise;
  };

  const playLineAudio = async (text: string, audioUrl?: string): Promise<void> => {
    const short = text.slice(0, 35);
    if (!text.trim()) {
      debugLog(`[AUDIO] playLineAudio SKIP — empty text`);
      return;
    }
    debugLog(`[AUDIO] playLineAudio START "${short}…"`);
    const t0 = Date.now();
    // Claim this playback; if the user navigates (stopAudio bumps the version)
    // while we're awaiting prefetchAudio, we discard the stale blob below.
    const version = ++audioPlayVersion.current;
    const audio = getOrCreateAudio();
    // Null handlers BEFORE pausing so stale onpause/onstalled from a
    // previous play can't fire and interfere.
    audio.onended = null;
    audio.onerror = null;
    audio.onpause = null;
    audio.onstalled = null;
    audio.pause();
    if (audio.src && audio.src.startsWith('blob:')) URL.revokeObjectURL(audio.src);
    try {
      const blob = await prefetchAudio(text, audioUrl);
      if (audioPlayVersion.current !== version) {
        debugLog(`[AUDIO] playLineAudio DISCARD stale "${short}…" — navigation/stop bumped version`);
        return;
      }
      debugLog(`[AUDIO] playLineAudio GOT BLOB "${short}…" — ${blob.size} bytes, fetched in ${Date.now() - t0}ms`);
      const url = URL.createObjectURL(blob);
      audio.src = url;
      return new Promise<void>((resolve) => {
        let resolved = false;
        const done = (reason: string) => {
          if (resolved) return;
          resolved = true;
          clearTimeout(safetyTimeout);
          audio.onended = null;
          audio.onerror = null;
          setPlayingSlideId(null);
          URL.revokeObjectURL(url);
          debugLog(`[AUDIO] playLineAudio DONE "${short}…" — reason=${reason}, total=${Date.now() - t0}ms`);
          resolve();
        };
        // Safety timeout — 12s is generous for a single TTS line (typically 3-8s)
        // but short enough that the student doesn't wait forever on failure.
        const safetyTimeout = setTimeout(() => {
          debugLog(`[AUDIO] playLineAudio SAFETY TIMEOUT "${short}…" — 12s elapsed`);
          done('safety-timeout');
        }, 12_000);
        // Only two legitimate termination events:
        // - onended: audio finished playing normally
        // - onerror: audio failed to decode/play
        // Removed onstalled (means "loading slowly", browser can recover — not terminal)
        // Removed onpause (mobile browsers fire spurious pause events)
        audio.onended = () => done('ended');
        audio.onerror = () => {
          debugLog(`[AUDIO] playLineAudio ERROR event "${short}…" — error=${audio.error?.message || 'unknown'}`);
          done('error');
        };
        audio.play()
          .then(() => {
            debugLog(`[AUDIO] playLineAudio PLAYING "${short}…" — duration=${audio.duration?.toFixed(1)}s`);
            setPlayingSlideId(carouselSlides[currentSlideIdx]?.id ?? null);
          })
          .catch((err) => {
            debugLog(`[AUDIO] playLineAudio PLAY REJECTED "${short}…" — ${err}`);
            done('play-rejected');
          });
      });
    } catch (err) {
      // TTS fetch failed (network timeout, server error, etc.)
      // Hold briefly so the typed-out line is still readable before advancing.
      debugLog(`[AUDIO] playLineAudio FETCH FAILED "${short}…" after ${Date.now() - t0}ms — ${err}`);
      await new Promise(r => setTimeout(r, 2000));
    }
  };

  // Scroll a widget into the center of its .focus-slide scroll container.
  // Mirrors the pattern TypewriterMarkdown uses for spotlight scrolling so the
  // widget lands in the student's focus zone rather than near the bottom edge.
  const scrollWidgetIntoFocus = (slideEl: HTMLElement, targetEl: HTMLElement) => {
    const parentRect = slideEl.getBoundingClientRect();
    const elRect = targetEl.getBoundingClientRect();
    const scrollTarget = targetEl.offsetTop - (parentRect.height / 2) + (elRect.height / 2);
    slideEl.scrollTo({ top: Math.max(0, scrollTarget), behavior: 'smooth' });
  };

  // Run the guided widget-reveal tour after a card's typewriter + audio finish.
  // Sequence: pause → scroll to ASCII visual (if any) → pause → auto-expand
  // Pixi visual (if any) → play narration → mark fullyReplayed.
  //
  // fastMode: the student tapped to skip the typewriter. We still expand the
  // widgets on mount (autoStart=true) but skip scroll/narration. The brief
  // initial pause gives React one commit cycle so autoStart=true mounts the
  // Pixi expanded BEFORE fullyReplayed flips it back to false.
  //
  // Cancels cleanly if the student navigates away or taps "I didn't understand".
  const runWidgetRevealSequence = async (slideIdx: number, fastMode = false) => {
    const slide = carouselSlides[slideIdx];
    if (!slide || slide.type !== 'explanation') {
      setFullyReplayed(prev => new Set(prev).add(slideIdx));
      return;
    }
    const hasAscii = !!slide.visual;
    const hasPixi = !!slide.visualExplanation?.pixi_code;
    if (!hasAscii && !hasPixi) {
      setFullyReplayed(prev => new Set(prev).add(slideIdx));
      return;
    }

    const token = { slideIdx, cancelled: false };
    widgetSequenceRef.current = token;
    const cancelled = () =>
      token.cancelled || widgetSequenceRef.current !== token;

    const getSlideEl = () =>
      (focusTrackRef.current?.children[slideIdx] as HTMLElement | undefined) || null;

    // Initial pause. Even in fast mode we yield once so the component
    // commits with autoStart=true before fullyReplayed is written below.
    await new Promise(r => setTimeout(r, fastMode ? 50 : 400));
    if (cancelled()) return;

    if (!fastMode) {
      // Step 1: ASCII visual box — scroll into focus, hold for reading.
      if (hasAscii) {
        const slideEl = getSlideEl();
        const asciiEl = slideEl?.querySelector('.explanation-card-visual') as HTMLElement | null;
        if (slideEl && asciiEl) {
          scrollWidgetIntoFocus(slideEl, asciiEl);
          asciiEl.classList.add('widget-focus-in');
          setTimeout(() => asciiEl.classList.remove('widget-focus-in'), 1400);
          await new Promise(r => setTimeout(r, 1800));
          if (cancelled()) return;
        }
      }

      // Step 2: Pixi visual — auto-expand (via fullyReplayed gate in render),
      // scroll into focus, play narration.
      if (hasPixi) {
        // Wait one frame so the expanded canvas mounts before we measure/scroll.
        await new Promise(r => requestAnimationFrame(() => r(null)));
        if (cancelled()) return;

        const slideEl = getSlideEl();
        const pixiEl = slideEl?.querySelector('.visual-explanation:not(.visual-explanation--collapsed)') as HTMLElement | null;
        if (slideEl && pixiEl) {
          scrollWidgetIntoFocus(slideEl, pixiEl);
          pixiEl.classList.add('widget-focus-in');
          setTimeout(() => pixiEl.classList.remove('widget-focus-in'), 1400);
        }

        const narration = slide.visualExplanation?.narration?.trim();
        if (narration) {
          await playLineAudio(narration);
        } else {
          await new Promise(r => setTimeout(r, 2500));
        }
        if (cancelled()) return;
      }
    }

    setFullyReplayed(prev => new Set(prev).add(slideIdx));
    if (widgetSequenceRef.current === token) widgetSequenceRef.current = null;
  };

  const handleFeedbackSubmit = async (action: 'continue' | 'restart') => {
    if (!sessionId || !feedbackText.trim()) return;
    setFeedbackSubmitting(true);
    setFeedbackError(null);
    try {
      const result = await submitFeedback(sessionId, feedbackText.trim(), action);
      setFeedbackCount(result.feedback_count);
      setFeedbackSuccess(true);
      setFeedbackText('');

      // On restart, reload the session to get the new welcome message & reset UI
      if (action === 'restart') {
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      } else {
        setTimeout(() => {
          setFeedbackModalOpen(false);
          setFeedbackSuccess(false);
        }, 2000);
      }
    } catch (err: any) {
      setFeedbackError(err.message || 'Failed to submit feedback');
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  const toggleFeedbackRecording = async () => {
    if (isFeedbackRecording) {
      feedbackRecorderRef.current?.stop();
      setIsFeedbackRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredTypes = ['audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t));
      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const activeMime = mediaRecorder.mimeType || 'audio/webm';
      feedbackChunksRef.current = [];
      const baseFeedback = feedbackText;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) feedbackChunksRef.current.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        feedbackRecorderRef.current = null;
        const audioBlob = new Blob(feedbackChunksRef.current, { type: activeMime });
        if (audioBlob.size === 0) return;
        setIsFeedbackTranscribing(true);
        try {
          const text = await transcribeAudio(audioBlob);
          if (text) {
            const spacer = baseFeedback && !baseFeedback.endsWith(' ') ? ' ' : '';
            setFeedbackText(`${baseFeedback}${spacer}${text}`);
          }
        } catch (err) {
          console.error('Feedback transcription failed:', err);
        } finally {
          setIsFeedbackTranscribing(false);
        }
      };
      feedbackRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsFeedbackRecording(true);
    } catch (err) {
      console.error('Microphone access denied:', err);
    }
  };

  // ─── Card phase action handler ─────────────────────────────────────
  const handleCardAction = async (action: 'clear' | 'explain_differently') => {
    if (!sessionId) return;
    setCardActionLoading(true);
    try {
      // Build check-in struggle events for tutor context
      let events: CheckInEventDTO[] | undefined;
      if (checkInStruggles.size > 0) {
        events = Array.from(checkInStruggles.entries()).map(([cardId, data]) => {
          // Find the card by card_id to get its card_idx field value
          const card = explanationCards.find(c => c.card_id === cardId);
          return {
            card_idx: card?.card_idx ?? 0,
            card_title: card?.title || `Check-in ${cardId}`,
            activity_type: card?.check_in?.activity_type || 'match_pairs',
            wrong_count: data.wrongCount,
            hints_shown: data.hintsShown,
            confused_pairs: data.confusedPairs.map(p => ({ left: p.left, right: p.right, wrong_count: p.wrongCount, wrong_picks: p.wrongPicks || [] })),
            auto_revealed: data.autoRevealed,
          };
        });
      }
      const result = await cardAction(sessionId, action, events);

      if (result.action === 'session_complete') {
        // Refresher topic completed — show completion message and end session
        setSessionPhase('interactive');
        setMessages((prev) => [
          ...prev,
          { role: 'teacher', content: result.message, audioText: result.audio_text || null },
        ]);
        setIsComplete(true);
        if (result.audio_text) {
          playTeacherAudio(result.audio_text, `complete-${Date.now()}`);
        }
      } else if (result.action === 'teach_me_complete') {
        // NEW: Teach Me card phase ended → show summary + Practice CTA
        // No bridge turn, no interactive phase. Student can click "Let's Practice"
        // or "I'm done for now".
        setIsComplete(true);
        setTeachMeComplete(true);
        setTeachMeCompletionMessage(result.message || null);
        setTeachMeConceptsCovered(result.concepts_covered || []);
        setTeachMeGuidelineId(result.guideline_id || null);
        if (result.coverage != null) setCoverage(result.coverage);
        if (result.audio_text) {
          playTeacherAudio(result.audio_text, `teach-complete-${Date.now()}`);
        }
      } else if (result.action === 'switch_variant' && result.cards) {
        setExplanationCards(annotateCards(result.cards));
        setCurrentSlideIdx(0);
        setVariantsShown(prev => prev + 1);
        // Clear check-in state — old variant's card_ids don't exist in new variant
        setCompletedCheckIns(new Set());
        setCheckInStruggles(new Map());
        localStorage.setItem(`slide-pos-${sessionId}`, '0');
      }
    } catch (err: any) {
      console.error('Card action failed:', err);
    } finally {
      setCardActionLoading(false);
    }
  };

  // ─── Practice CTA handler ────────────────────────────────────────
  // Teach Me complete → hand off to Practice v2 drill route.
  const handleStartPracticeFromCTA = () => {
    if (!teachMeGuidelineId) return;
    const prettyTopic = /[-_]/.test(topic)
      ? topic.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
      : topic;
    navigate(`/practice/${teachMeGuidelineId}`, {
      state: { topicTitle: prettyTopic, subject, chapter, topic },
    });
  };

  const handleDoneForNow = () => {
    if (!subject || !chapter || !topic) {
      navigate('/learn');
      return;
    }
    navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}`);
  };

  const handleSimplifyCard = async () => {
    if (!sessionId || simplifyLoading) return;
    const cardIdx = currentSlideIdx;
    if (cardIdx < 0 || cardIdx >= explanationCards.length) return;

    const currentCard = explanationCards[cardIdx];
    const baseCardIdx = currentCard.source_card_idx ?? cardIdx;

    // Cancel any in-flight widget reveal tour — student just asked for
    // simplification, so the original card's tour is no longer the focus.
    if (widgetSequenceRef.current) {
      widgetSequenceRef.current.cancelled = true;
      widgetSequenceRef.current = null;
    }

    setSimplifyJustAdded(false);
    setSimplifyLoading(true);
    try {
      const result = await simplifyCard(sessionId, baseCardIdx);

      if (result.action === 'append_to_card' && result.simplification) {
        setExplanationCards(prev => {
          const updated = [...prev];
          if (cardIdx >= 0 && cardIdx < updated.length) {
            const card = { ...updated[cardIdx] };
            card.simplifications = [...(card.simplifications || []), result.simplification];
            updated[cardIdx] = card;
          }
          return updated;
        });
        setSimplifyJustAdded(true);
        // Auto-scroll to new section
        setTimeout(() => {
          const slide = document.querySelector(`.focus-slide:nth-child(${currentSlideIdx + 1})`);
          if (slide) {
            slide.scrollTo({ top: slide.scrollHeight, behavior: 'smooth' });
          }
        }, 100);
      }
    } catch (err: any) {
      console.error('Simplify card failed:', err);
    } finally {
      setSimplifyLoading(false);
    }
  };

  if (replayLoading) {
    return (
      <div className="app">
        <header className="header">
          <h1>Learn Like Magic</h1>
          <p className="subtitle">Loading session...</p>
        </header>
        <div className="chat-container" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <p>Loading session...</p>
        </div>
      </div>
    );
  }

  // Baatcheet (dialogue) phase — render the standalone viewer. Skips the
  // entire explanation-card carousel below; the viewer owns its own deck +
  // audio + check-in + progress posting.
  if (sessionPhase === 'dialogue_phase' && dialogueCards && dialoguePersonalization) {
    return (
      <div className="app baatcheet-active">
        <BaatcheetViewer
          sessionId={sessionId || ''}
          cards={dialogueCards}
          personalization={dialoguePersonalization}
          initialCardIdx={dialogueInitialIdx}
        />
      </div>
    );
  }

  return (
    <>
      <div className={`app${sessionPhase === 'card_phase' ? ' chalkboard-active' : ''}`}>
        <nav className="nav-bar">
          <button className="nav-home-btn" onClick={() => navigate('/learn')} aria-label="Home">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
          </button>

          <span className="nav-center nav-breadcrumb">
            {subject && <>{subject}</>}
            {chapter && <> &rsaquo; {chapter}</>}
            {topic && <> &rsaquo; {topic}</>}
          </span>

          <div className="nav-actions">
            {sessionId && !isComplete && (
              <button
                onClick={() => setFeedbackModalOpen(true)}
                className="nav-action-btn feedback-btn"
                disabled={feedbackCount >= 3}
                title={feedbackCount >= 3 ? 'Feedback limit reached' : 'Share feedback'}
              >
                Feedback
              </button>
            )}
            {sessionId && !isComplete && carouselSlides.length > 0 && (
              <>
                <button
                  className={`focus-audio-btn${playingSlideId === carouselSlides[currentSlideIdx]?.id ? ' playing' : ''}`}
                  onClick={() => {
                    const slide = carouselSlides[currentSlideIdx];
                    if (!slide) return;
                    if (playingSlideId === slide.id) {
                      stopAudio();
                      return;
                    }
                    // During active typewriter: stop audio + skip
                    if (slide.type === 'explanation' && !revealedSlides.has(currentSlideIdx)) {
                      setTypewriterSkip(prev => new Set(prev).add(currentSlideIdx));
                      stopAudioWithFade();
                      return;
                    }
                    // After completion: play full card audio (audioText is already TTS-friendly)
                    playTeacherAudio(slide.audioText || slide.content, slide.id, slide.audioUrl);
                  }}
                  aria-label={playingSlideId === carouselSlides[currentSlideIdx]?.id ? 'Stop audio' : 'Play audio'}
                >
                  {playingSlideId === carouselSlides[currentSlideIdx]?.id ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                      <rect x="6" y="5" width="4" height="14" rx="1" />
                      <rect x="14" y="5" width="4" height="14" rx="1" />
                    </svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                    </svg>
                  )}
                </button>
                <span className="focus-counter">{currentSlideIdx + 1}/{carouselSlides.length}</span>
              </>
            )}
            {sessionId && (
              <button
                onClick={() => setDevToolsOpen(true)}
                className="nav-action-btn"
                title="Dev Tools"
              >
                Dev
              </button>
            )}
          </div>
        </nav>

        <div className="progress-bar">
          <div className="progress-info">
            {/* Step indicator hidden — internal tutor state, not shown to student */}
            {sessionMode === 'clarify_doubts' && (
              <span>
                {conceptsDiscussed.length > 0
                  ? conceptsDiscussed.map((c, i) => (
                      <span key={i} style={{
                        display: 'inline-block',
                        background: '#e2e8f0',
                        borderRadius: '12px',
                        padding: '2px 8px',
                        margin: '0 4px',
                        fontSize: '0.75rem',
                      }}>{c}</span>
                    ))
                  : 'Ask your questions!'}
              </span>
            )}
          </div>
        </div>

        <div className="chat-container" data-testid="chat-container">
          {teachMeComplete ? (
            <div className="summary-card" data-testid="teach-me-complete">
              <h2>Nice work!</h2>
              {teachMeConceptsCovered.length > 0 && (
                <div className="summary-content">
                  <p>You've covered:</p>
                  <div className="summary-chips">
                    {teachMeConceptsCovered.map((c, i) => (
                      <span key={i} className="summary-chip">{c}</span>
                    ))}
                  </div>
                </div>
              )}
              {teachMeCompletionMessage && (
                <p className="summary-card-message">
                  {teachMeCompletionMessage}
                </p>
              )}
              <button
                onClick={handleStartPracticeFromCTA}
                className="restart-button"
                data-testid="start-practice-cta"
              >
                Let's Practice — put it to work!
              </button>
              <button
                onClick={handleDoneForNow}
                className="restart-button restart-button--ghost"
              >
                I'm done for now
              </button>
            </div>
          ) : showSummary ? (
            <div className="summary-card" data-testid="session-summary">
              {sessionMode === 'clarify_doubts' ? (
                <>
                  <h2>Doubts Session Complete!</h2>
                  {conceptsDiscussed.length > 0 && (
                    <div className="summary-content">
                      <p><strong>Concepts Discussed:</strong></p>
                      <div className="summary-chips">
                        {conceptsDiscussed.map((c, i) => (
                          <span key={i} className="summary-chip">{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  <button onClick={handleBack} className="restart-button">
                    Back to Topic
                  </button>
                </>
              ) : (
                <>
                  <h2>Well done!</h2>
                  {summary && summary.concepts_taught && summary.concepts_taught.length > 0 && (
                    <div className="summary-content">
                      <p>You covered:</p>
                      <div className="summary-chips">
                        {summary.concepts_taught.map((c, i) => (
                          <span key={i} className="summary-chip">{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  <button onClick={handleBack} className="restart-button">
                    Continue Practicing
                  </button>
                  <button
                    onClick={() => navigate(subject && chapter
                      ? `/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}`
                      : '/learn'
                    )}
                    className="restart-button restart-button--ghost"
                  >
                    Explore More Topics
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="focus-carousel">
              <div className="focus-track-container">
                <div
                  ref={focusTrackRef}
                  className="focus-track"
                  style={{
                    transform: `translateX(${-(Math.min(currentSlideIdx, carouselSlides.length - 1) * 100)}%)`,
                    transition: 'transform 0.3s ease-out',
                  }}
                >
                  {carouselSlides.map((slide, i) => (
                    <div
                      key={slide.id}
                      className="focus-slide"
                      onClick={() => {
                        // Tap to skip typewriter on explanation cards
                        if (slide.type === 'explanation' && i === currentSlideIdx && !revealedSlides.has(i)) {
                          setTypewriterSkip(prev => new Set(prev).add(i));
                          stopAudioWithFade();
                        }
                      }}
                    >
                      {slide.type === 'explanation' ? (
                        <>
                          {slide.cardType !== 'welcome' && (
                          <div className="explanation-card-type">
                            <span>
                              {slide.cardType === 'concept' ? 'Concept' :
                               slide.cardType === 'example' ? 'Example' :
                               slide.cardType === 'visual' ? 'Visual' :
                               slide.cardType === 'analogy' ? 'Analogy' :
                               slide.cardType === 'summary' ? 'Summary' :
                               slide.cardType === 'simplification' ? 'Simplified' : slide.cardType}
                            </span>
                          </div>
                          )}
                          <div className="focus-tutor-msg">
                            <TypewriterMarkdown
                              content={slide.content}
                              title={slide.title}
                              isActive={i === currentSlideIdx}
                              skipAnimation={revealedSlides.has(i) || typewriterSkip.has(i) || sessionPhase !== 'card_phase'}
                              audioLines={slide.audioLines}
                              onRevealComplete={() => {
                                setRevealedSlides(prev => new Set(prev).add(i));
                                if (i === currentSlideIdx) {
                                  // fast mode: student tapped to skip — expand widgets
                                  // immediately, no guided narration/scroll.
                                  runWidgetRevealSequence(i, typewriterSkip.has(i));
                                } else {
                                  // Reveal happened on a non-active slide (rare); no tour needed.
                                  setFullyReplayed(prev => new Set(prev).add(i));
                                }
                              }}
                              onBlockStart={(audioText: string, blockIdx: number) => {
                                const offset = slide.title?.trim() ? 1 : 0;
                                const curLine = slide.audioLines?.[blockIdx - offset];
                                if (audioText.trim()) prefetchAudio(audioText, curLine?.audio_url);
                                // Look-ahead: prefetch next line so audio is ready before typing finishes
                                const nextLine = slide.audioLines?.[blockIdx - offset + 1];
                                if (nextLine?.audio?.trim()) prefetchAudio(nextLine.audio, nextLine.audio_url);
                              }}
                              onBlockTyped={async (audioText: string, blockIdx: number) => {
                                if (!audioText.trim()) return;
                                const offset = slide.title?.trim() ? 1 : 0;
                                const line = slide.audioLines?.[blockIdx - offset];
                                await playLineAudio(audioText, line?.audio_url);
                              }}
                            />
                          </div>
                          {revealedSlides.has(i) && slide.visual && (
                            <pre className="explanation-card-visual">{slide.visual}</pre>
                          )}
                          {revealedSlides.has(i) && slide.visualExplanation && (
                            <VisualExplanationComponent
                              visual={slide.visualExplanation}
                              autoStart={!fullyReplayed.has(i) && i === currentSlideIdx}
                            />
                          )}
                          {/* Inline simplification sections */}
                          {slide.simplifications?.map((simplification: any, sIdx: number) => {
                            const isLast = sIdx === (slide.simplifications?.length || 0) - 1;
                            const shouldAnimate = isLast && (simplifyJustAdded || preloadAnimateCards.has(i));
                            const separatorTexts = [
                              'Let me break this down',
                              'Even simpler',
                              'One more way to think about it',
                              'Let\u2019s try another angle',
                            ];
                            return (
                              <div key={`simplification-${sIdx}`} className="inline-simplification">
                                <div className="simplification-separator">
                                  <span>{separatorTexts[Math.min(sIdx, separatorTexts.length - 1)]}</span>
                                </div>
                                <div className="focus-tutor-msg">
                                  <TypewriterMarkdown
                                    content={simplification.content || ''}
                                    title={simplification.title}
                                    isActive={i === currentSlideIdx && shouldAnimate}
                                    skipAnimation={!shouldAnimate}
                                    audioLines={simplification.lines}
                                    onRevealComplete={() => {
                                      setSimplifyJustAdded(false);
                                      setPreloadAnimateCards(prev => {
                                        const next = new Set(prev);
                                        next.delete(i);
                                        return next;
                                      });
                                    }}
                                    onBlockStart={(audioText: string, blockIdx: number) => {
                                      const offset = simplification.title?.trim() ? 1 : 0;
                                      const curLine = simplification.lines?.[blockIdx - offset];
                                      if (audioText.trim()) prefetchAudio(audioText, curLine?.audio_url);
                                      // Look-ahead: prefetch next line
                                      const nextLine = simplification.lines?.[blockIdx - offset + 1];
                                      if (nextLine?.audio?.trim()) prefetchAudio(nextLine.audio, nextLine.audio_url);
                                    }}
                                    onBlockTyped={async (audioText: string, blockIdx: number) => {
                                      if (!audioText.trim()) return;
                                      const offset = simplification.title?.trim() ? 1 : 0;
                                      const line = simplification.lines?.[blockIdx - offset];
                                      await playLineAudio(audioText, line?.audio_url);
                                    }}
                                  />
                                </div>
                                {simplification.visual_explanation && (
                                  <VisualExplanationComponent visual={simplification.visual_explanation} />
                                )}
                              </div>
                            );
                          })}
                          {/* Loading skeleton while generating simplification */}
                          {simplifyLoading && i === currentSlideIdx && (
                            <div className="inline-simplification">
                              <div className="simplification-separator">
                                <span>Let me break this down</span>
                              </div>
                              <div className="simplification-skeleton">
                                <div className="skeleton-line" />
                                <div className="skeleton-line short" />
                                <div className="skeleton-line" />
                              </div>
                            </div>
                          )}
                        </>
                      ) : slide.type === 'check_in' && slide.checkIn ? (
                        <>
                          <div className="explanation-card-type">
                            <span style={{ background: '#CCFBF1', color: '#115E59' }}>Check-in</span>
                          </div>
                          <CheckInDispatcher
                            checkIn={slide.checkIn}
                            onComplete={(result) => {
                              setCompletedCheckIns(prev => new Set(prev).add(slide.id));
                              setCheckInStruggles(prev => new Map(prev).set(slide.id, result));
                            }}
                          />
                        </>
                      ) : (
                        <>
                          <div className="focus-tutor-msg">
                            <ReactMarkdown>{slide.content}</ReactMarkdown>
                            {slide.visualExplanation && (
                              <VisualExplanationComponent visual={slide.visualExplanation} />
                            )}
                          </div>
                          {slide.studentResponse && (
                            <div className="focus-student-msg">
                              <div className="focus-student-label">You</div>
                              {slide.studentResponse}
                            </div>
                          )}
                        </>
                      )}
                      {/* Typing indicator on last slide */}
                      {i === carouselSlides.length - 1 && loading && !streamingText && (
                        <div className="focus-typing">
                          <div className="typing-indicator">
                            <span></span><span></span><span></span>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Bottom action area — greyed out during typewriter animation */}
              {(() => {
                const isAnimating = carouselSlides[currentSlideIdx]?.type === 'explanation' && !revealedSlides.has(currentSlideIdx);
                return sessionPhase === 'card_phase' ? (
                currentSlideIdx < explanationCards.length ? ( /* last card is at index explanationCards.length (welcome=0) */
                  <div className="explanation-nav">
                    {currentSlideIdx > 0 && !simplifyLoading && !isAnimating
                      && carouselSlides[currentSlideIdx]?.type !== 'check_in' && (
                      <button
                        className="explanation-nav-btn simplify"
                        onClick={() => handleSimplifyCard()}
                        disabled={cardActionLoading}
                      >
                        I didn't understand
                      </button>
                    )}
                    {simplifyLoading && (
                      <div className="explanation-nav-btn simplify" style={{opacity: 0.6}}>Simplifying...</div>
                    )}
                    <div className="explanation-nav-row">
                      <button
                        className="explanation-nav-btn secondary"
                        onClick={() => {
                          const prev = Math.max(currentSlideIdx - 1, 0);
                          setCurrentSlideIdx(prev);
                          if (sessionId) localStorage.setItem(`slide-pos-${sessionId}`, String(prev));
                        }}
                        disabled={currentSlideIdx === 0 || simplifyLoading || isAnimating}
                      >
                        Back
                      </button>
                      <button
                        className="explanation-nav-btn primary"
                        onClick={() => {
                          const next = Math.min(currentSlideIdx + 1, explanationCards.length); /* +1 welcome offset */
                          setCurrentSlideIdx(next);
                          if (sessionId) localStorage.setItem(`slide-pos-${sessionId}`, String(next));
                        }}
                        disabled={simplifyLoading || isAnimating || (carouselSlides[currentSlideIdx]?.type === 'check_in' && !completedCheckIns.has(carouselSlides[currentSlideIdx]?.id || ''))}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="explanation-nav">
                    {!simplifyLoading
                      && carouselSlides[currentSlideIdx]?.type !== 'check_in' && (
                      <button
                        className="explanation-nav-btn simplify"
                        onClick={() => handleSimplifyCard()}
                        disabled={cardActionLoading}
                      >
                        I didn't understand
                      </button>
                    )}
                    {simplifyLoading && (
                      <div className="explanation-nav-btn simplify" style={{opacity: 0.6}}>Simplifying...</div>
                    )}
                    <div className="explanation-actions">
                      <button
                        className="explanation-nav-btn primary"
                        onClick={() => handleCardAction('clear')}
                        disabled={cardActionLoading || simplifyLoading}
                      >
                        {isRefresher ? "I'm Ready" : 'Start practice'}
                      </button>
                      {!isRefresher && (
                        <button
                          className="explanation-nav-btn secondary"
                          onClick={() => handleCardAction('explain_differently')}
                          disabled={cardActionLoading || simplifyLoading}
                        >
                          {variantsShown >= (cardPhaseState?.available_variants ?? 0) ? "I still need help" : "Try a different approach"}
                        </button>
                      )}
                    </div>
                  </div>
                )
              ) : !loading ? (
                currentSlideIdx < carouselSlides.length - 1 ? (
                  /* User navigated back to a previous slide — show nav only */
                  <div className="explanation-nav">
                    <div className="explanation-nav-row">
                      <button
                        className="explanation-nav-btn secondary"
                        onClick={() => setCurrentSlideIdx(Math.max(currentSlideIdx - 1, 0))}
                        disabled={currentSlideIdx === 0}
                      >
                        Back
                      </button>
                      <button
                        className="explanation-nav-btn primary"
                        onClick={() => setCurrentSlideIdx(currentSlideIdx + 1)}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                ) : activeQuestionFormat ? (
                  <div className="focus-input-area">
                    <InteractiveQuestion
                      questionFormat={activeQuestionFormat}
                      onSubmit={(answerText) => sendMessage(answerText)}
                    />
                  </div>
                ) : (
                <div className="focus-input-area">
                  <form className={`input-form${isRecording ? ' recording' : ''}`} onSubmit={handleSubmit}>
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder={isRecording ? 'Listening...' : isTranscribing ? 'Transcribing...' : 'Type your answer...'}
                      disabled={loading || isTranscribing}
                      className="input-field"
                      data-testid="chat-input"
                    />
                    <button
                      type="button"
                      onClick={toggleRecording}
                      disabled={loading || isTranscribing}
                      className={`mic-button${isRecording ? ' recording' : ''}${isTranscribing ? ' transcribing' : ''}`}
                      data-testid="mic-button"
                      title={isRecording ? 'Stop recording' : isTranscribing ? 'Transcribing...' : 'Voice input'}
                      aria-label={isRecording ? 'Stop recording' : 'Start voice input'}
                    >
                      {isTranscribing ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="10" />
                          <path d="M12 6v6l4 2" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                          <line x1="12" y1="19" x2="12" y2="23" />
                          <line x1="8" y1="23" x2="16" y2="23" />
                        </svg>
                      )}
                    </button>
                    <button type="submit" disabled={loading || isTranscribing || !input.trim()} className="send-button" data-testid="send-button" aria-label="Send">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="12" y1="19" x2="12" y2="5" />
                        <polyline points="5 12 12 5 19 12" />
                      </svg>
                    </button>
                  </form>
                </div>
                )
              ) : null;
              })()}
              {isComplete && sessionMode === 'teach_me' && summary && (
                <div className="session-complete-card">
                  <h3 className="session-complete-title">Well done!</h3>
                  {summary.concepts_taught && summary.concepts_taught.length > 0 && (
                    <div className="session-complete-concepts">
                      <p className="session-complete-label">You covered:</p>
                      <div className="session-complete-chips">
                        {summary.concepts_taught.map((c, i) => (
                          <span key={i} className="session-complete-chip">{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  <p className="session-complete-prompt">
                    What would you like to do next?
                  </p>
                  <div className="session-complete-actions">
                    <button
                      className="session-complete-btn session-complete-btn--primary"
                      onClick={handleBack}
                    >
                      Continue Practicing
                    </button>
                    <button
                      className="session-complete-btn session-complete-btn--ghost"
                      onClick={() => navigate(subject && chapter
                        ? `/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}`
                        : '/learn'
                      )}
                    >
                      Explore More Topics
                    </button>
                  </div>
                </div>
              )}
              {isComplete && sessionMode !== 'teach_me' && (
                <div className="session-complete-summary-wrap">
                  <button
                    className="session-complete-btn session-complete-btn--primary"
                    onClick={() => setShowSummary(true)}
                  >
                    View Session Summary
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {sessionId && (
        <DevToolsDrawer
          sessionId={sessionId}
          isOpen={devToolsOpen}
          onClose={() => setDevToolsOpen(false)}
        />
      )}
      {/* Feedback Modal */}
      {feedbackModalOpen && (
        <div className="feedback-modal-backdrop" onClick={() => !feedbackSubmitting && setFeedbackModalOpen(false)}>
          <div className="feedback-modal" onClick={(e) => e.stopPropagation()}>
            <div className="feedback-modal-header">
              <h3 className="feedback-modal-title">Share Feedback</h3>
              <button
                className="feedback-modal-close"
                onClick={() => !feedbackSubmitting && setFeedbackModalOpen(false)}
                aria-label="Close"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <p className="feedback-hint">Tell us how the session is going (e.g., &ldquo;too fast&rdquo;, &ldquo;use more examples&rdquo;, &ldquo;my child knows this already&rdquo;)</p>
            {feedbackSuccess ? (
              <div className="feedback-success">Plan updated successfully!</div>
            ) : (
              <>
                <textarea
                  className="feedback-textarea"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value.slice(0, 500))}
                  placeholder="Type your feedback..."
                  maxLength={500}
                  rows={4}
                  disabled={feedbackSubmitting}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                  <button
                    type="button"
                    onClick={toggleFeedbackRecording}
                    disabled={feedbackSubmitting || isFeedbackTranscribing}
                    className={`mic-button${isFeedbackRecording ? ' recording' : ''}${isFeedbackTranscribing ? ' transcribing' : ''}`}
                    title={isFeedbackRecording ? 'Stop recording' : isFeedbackTranscribing ? 'Transcribing...' : 'Voice input'}
                    aria-label={isFeedbackRecording ? 'Stop recording' : 'Start voice input'}
                  >
                    {isFeedbackTranscribing ? (
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 6v6l4 2" />
                      </svg>
                    ) : (
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                        <line x1="12" y1="19" x2="12" y2="23" />
                        <line x1="8" y1="23" x2="16" y2="23" />
                      </svg>
                    )}
                  </button>
                  <span style={{ fontSize: '0.75rem', color: '#718096' }}>{feedbackText.length}/500</span>
                  <span style={{ fontSize: '0.75rem', color: '#718096', marginLeft: 'auto' }}>{3 - feedbackCount} feedback{3 - feedbackCount !== 1 ? 's' : ''} remaining</span>
                </div>
                {feedbackError && <div className="feedback-error">{feedbackError}</div>}
                <div className="feedback-action-buttons">
                  <button
                    className="feedback-submit-btn feedback-continue-btn"
                    onClick={() => handleFeedbackSubmit('continue')}
                    disabled={feedbackSubmitting || !feedbackText.trim() || isFeedbackTranscribing}
                  >
                    {feedbackSubmitting ? 'Updating...' : 'Continue Session'}
                  </button>
                  <button
                    className="feedback-submit-btn feedback-restart-btn"
                    onClick={() => handleFeedbackSubmit('restart')}
                    disabled={feedbackSubmitting || !feedbackText.trim() || isFeedbackTranscribing}
                  >
                    {feedbackSubmitting ? 'Restarting...' : 'Restart Session'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
