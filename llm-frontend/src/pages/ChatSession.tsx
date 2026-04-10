import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useParams, useLocation, useOutletContext } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
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
  createSession,
  endPracticeSession,
  TutorWebSocket,
  Turn,
  ExplanationCard,
  CardPhaseDTO,
  SummaryResponse,
  VisualExplanation as VisualExplanationType,
  QuestionFormat,
  CheckInActivity,
  CheckInEventDTO,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';
import { useAuth } from '../contexts/AuthContext';
import DevToolsDrawer from '../features/devtools/components/DevToolsDrawer';
import VisualExplanationComponent from '../components/VisualExplanation';
import InteractiveQuestion from '../components/InteractiveQuestion';
import CheckInDispatcher, { CheckInActivityResult } from '../components/CheckInDispatcher';
import TypewriterMarkdown from '../components/TypewriterMarkdown';
import '../App.css';

interface Message {
  role: 'teacher' | 'student';
  content: string;
  audioText?: string | null;
  hints?: string[];
  visualExplanation?: VisualExplanationType | null;
  questionFormat?: QuestionFormat | null;
}

interface ExamQuestionDraft {
  question_idx: number;
  question_text: string;
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
  audioLines?: { display: string; audio: string }[];  // Per-line audio from LLM
  checkIn?: CheckInActivity | null;
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
  const [sessionMode, setSessionMode] = useState<'teach_me' | 'clarify_doubts' | 'exam' | 'practice'>(
    (locState?.mode as any) || 'teach_me',
  );
  const [coverage, setCoverage] = useState(0);
  const [conceptsDiscussed, setConceptsDiscussed] = useState<string[]>([]);
  const [examProgress, setExamProgress] = useState<{ current: number; total: number; answered: number } | null>(null);
  const [examFeedback, setExamFeedback] = useState<{ score: number; total: number; percentage: number } | null>(null);
  const [examResults, setExamResults] = useState<Array<{ question_idx: number; question_text: string; student_answer?: string | null; result?: 'correct' | 'partial' | 'incorrect' | null; score?: number; marks_rationale?: string; feedback?: string; expected_answer?: string }>>([]);
  const [examQuestions, setExamQuestions] = useState<ExamQuestionDraft[]>([]);
  const [examDraftAnswers, setExamDraftAnswers] = useState<Record<number, string>>({});
  const [activeExamQuestionIdx, setActiveExamQuestionIdx] = useState(0);
  const [examSubmittedIdxs, setExamSubmittedIdxs] = useState<Set<number>>(new Set());
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [examHydrationError, setExamHydrationError] = useState(false);
  const [examSubmitError, setExamSubmitError] = useState<string | null>(null);
  const [playingSlideId, setPlayingSlideId] = useState<string | null>(null);

  // Card phase state (pre-computed explanations)
  const [sessionPhase, setSessionPhase] = useState<'card_phase' | 'interactive'>('interactive');
  const [explanationCards, setExplanationCards] = useState<ExplanationCard[]>([]);
  const [cardPhaseState, setCardPhaseState] = useState<CardPhaseDTO | null>(null);
  const [cardActionLoading, setCardActionLoading] = useState(false);
  const [simplifyLoading, setSimplifyLoading] = useState(false);
  const [variantsShown, setVariantsShown] = useState(1);

  // Teach Me completion screen state (shown after card phase ends — summary + Practice CTA)
  const [teachMeComplete, setTeachMeComplete] = useState(false);
  const [teachMeCompletionMessage, setTeachMeCompletionMessage] = useState<string | null>(null);
  const [teachMeConceptsCovered, setTeachMeConceptsCovered] = useState<string[]>([]);
  const [teachMeGuidelineId, setTeachMeGuidelineId] = useState<string | null>(null);
  const [creatingPractice, setCreatingPractice] = useState(false);
  const [practiceStartError, setPracticeStartError] = useState<string | null>(null);

  // Practice completion screen state (shown when mastery achieved or ended early)
  const [practiceComplete, setPracticeComplete] = useState(false);
  const [practiceSummary, setPracticeSummary] = useState<string | null>(null);
  const [practiceQuestionsAnswered, setPracticeQuestionsAnswered] = useState(0);
  const [endingPractice, setEndingPractice] = useState(false);
  // Typewriter: track which slide indices have been fully revealed
  const [revealedSlides, setRevealedSlides] = useState<Set<number>>(new Set());
  const [typewriterSkip, setTypewriterSkip] = useState<Set<number>>(new Set());
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
  const containerRef = useRef<HTMLDivElement>(null);
  const focusSwipeStartX = useRef(0);
  const focusSwipeStartY = useRef(0);
  const focusSwipeDir = useRef<'h' | 'v' | null>(null);
  const prevSlidesLen = useRef(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const examEndRef = useRef<HTMLDivElement>(null);
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
    if (sessionMode === 'exam' || isComplete) return;
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
          playTeacherAudio(newSlide.audioText || newSlide.content, newSlide.id);
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
    const slide = carouselSlides[currentSlideIdx];
    // Auto-play for message and check_in slides; explanation slides use per-line typewriter audio
    if (slide && (slide.type === 'message' || slide.type === 'check_in')) {
      playTeacherAudio(slide.audioText || slide.content, slide.id);
    }
  }, [currentSlideIdx, sessionPhase, carouselSlides]);

  const hydrateExamState = (state: any) => {
    if (!state?.exam_questions) return;

    const questions = state.exam_questions.map((q: any) => ({
      question_idx: q.question_idx,
      question_text: q.question_text,
    }));
    setExamQuestions(questions);

    const existingAnswers: Record<number, string> = {};
    const alreadySubmitted = new Set<number>();
    state.exam_questions.forEach((q: any) => {
      if (q.student_answer) {
        existingAnswers[q.question_idx] = q.student_answer;
        alreadySubmitted.add(q.question_idx);
      }
    });
    setExamDraftAnswers(existingAnswers);
    setExamSubmittedIdxs(alreadySubmitted);

    const answeredCount = Object.values(existingAnswers).filter((a) => a.trim().length > 0).length;
    const firstUnansweredIdx = questions.findIndex((q: ExamQuestionDraft) => !(existingAnswers[q.question_idx] || '').trim());
    const nextIdx = firstUnansweredIdx >= 0 ? firstUnansweredIdx : questions.length;
    setActiveExamQuestionIdx(nextIdx);

    setExamProgress({
      current: Math.min(nextIdx + 1, questions.length || 1),
      total: questions.length,
      answered: answeredCount,
    });
  };

  const retryExamHydration = () => {
    if (!sessionId) return;
    setExamHydrationError(false);
    setReplayLoading(true);
    getSessionReplay(sessionId)
      .then((state) => {
        if (state.mode === 'exam' && state.exam_questions) {
          hydrateExamState(state);
        }
      })
      .catch((err) => {
        console.error('Retry failed:', err);
        setExamHydrationError(true);
      })
      .finally(() => setReplayLoading(false));
  };

  useEffect(() => { examEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [activeExamQuestionIdx, examDraftAnswers]);

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
      // Check for card phase (pre-computed explanations)
      if (locState.firstTurn.session_phase === 'card_phase' && locState.firstTurn.explanation_cards) {
        setSessionPhase('card_phase');
        setExplanationCards(annotateCards(locState.firstTurn.explanation_cards));
        setCurrentSlideIdx(0);
        setCardPhaseState(locState.firstTurn.card_phase_state || null);
        setVariantsShown(1);
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
      if (locState.mode === 'exam' && locState.firstTurn.exam_progress) {
        setExamProgress({
          current: locState.firstTurn.exam_progress.current_question,
          total: locState.firstTurn.exam_progress.total_questions,
          answered: locState.firstTurn.exam_progress.answered_questions,
        });
      }

      if (locState.mode === 'exam' && locState.firstTurn.exam_questions) {
        hydrateExamState({ exam_questions: locState.firstTurn.exam_questions });
      }

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
          if (state.mode === 'exam' && state.exam_questions) {
            hydrateExamState(state);
            if (state.exam_finished) {
              setExamResults(
                state.exam_questions.map((q: any) => ({
                  question_idx: q.question_idx,
                  question_text: q.question_text,
                  student_answer: q.student_answer,
                  result: q.result,
                  score: q.score,
                  marks_rationale: q.marks_rationale,
                  feedback: q.feedback,
                  expected_answer: q.expected_answer,
                })),
              );
            }
          }

          // Hydrate card phase — active or completed
          if (state._replay_explanation_cards) {
            setExplanationCards(annotateCards(state._replay_explanation_cards));

            if (state.card_phase?.active) {
              // Card phase still in progress — restore card navigation state
              let slideIdx = 0;
              if (state.card_phase.current_card_idx != null) {
                slideIdx = state.card_phase.current_card_idx + 1; // +1 for welcome slide
              } else {
                const savedPos = localStorage.getItem(`slide-pos-${sessionId}`);
                if (savedPos) slideIdx = parseInt(savedPos, 10);
              }
              setSessionPhase('card_phase');
              setCurrentSlideIdx(slideIdx);
              prevSlidesLen.current = state._replay_explanation_cards.length + 1; // +1 for welcome slide
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
          // Fall back to legacy checks only if the field is missing (shouldn't
          // happen with the new replay API but safe to keep).
          const completed = state.is_complete
            ?? (state.clarify_complete
                || state.exam_finished
                || state.practice_mastery_achieved
                || (state.topic && state.current_step > (state.topic?.study_plan?.steps?.length ?? Infinity)));
          if (completed) {
            setIsComplete(true);
            // Reconstruct exam summary from persisted feedback
            if (state.exam_finished && state.exam_feedback) {
              setSummary({
                steps_completed: state.exam_feedback.total,
                mastery_score: state.exam_feedback.percentage / 100,
                misconceptions_seen: state.exam_feedback.weak_areas || [],
                suggestions: state.exam_feedback.next_steps || [],
              });
              setExamFeedback({
                score: state.exam_feedback.score,
                total: state.exam_feedback.total,
                percentage: state.exam_feedback.percentage,
              });
            }
            // Reconstruct practice completion state on resume
            if (state.mode === 'practice' && state.practice_mastery_achieved) {
              setPracticeComplete(true);
              setPracticeQuestionsAnswered(state.practice_questions_answered || 0);
            }
          }
        })
        .catch((err) => {
          console.error('Failed to load session:', err);
          if (sessionMode === 'exam') {
            setExamHydrationError(true);
          }
        })
        .finally(() => setReplayLoading(false));
    }

    // Clear location state so refresh doesn't re-trigger
    navigate(location.pathname, { replace: true, state: null });
  }, [sessionId]);

  // Connect WebSocket for streaming (non-exam modes)
  useEffect(() => {
    if (!sessionId || sessionMode === 'exam') return;

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
      if (response.next_turn.exam_progress) {
        setExamProgress({
          current: response.next_turn.exam_progress.current_question,
          total: response.next_turn.exam_progress.total_questions,
          answered: response.next_turn.exam_progress.answered_questions,
        });
      }
      if (response.next_turn.is_complete) {
        setIsComplete(true);
        if (sessionMode === 'exam') {
          if (response.next_turn.exam_feedback) {
            setSummary({
              steps_completed: response.next_turn.exam_feedback.total,
              mastery_score: response.next_turn.exam_feedback.percentage / 100,
              misconceptions_seen: response.next_turn.exam_feedback.weak_areas || [],
              suggestions: response.next_turn.exam_feedback.next_steps || [],
            });
            setExamFeedback({
              score: response.next_turn.exam_feedback.score,
              total: response.next_turn.exam_feedback.total,
              percentage: response.next_turn.exam_feedback.percentage,
            });
          }
          setExamResults(response.next_turn.exam_results || []);
        } else if (sessionMode === 'practice') {
          // Practice mastery achieved — show practice completion screen
          setPracticeComplete(true);
          setPracticeSummary(response.next_turn.message);
        } else if (sessionMode !== 'clarify_doubts') {
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

    if (sessionMode === 'exam') {
      const currentQuestion = examQuestions[activeExamQuestionIdx];
      if (!currentQuestion) return;

      const updatedAnswers = {
        ...examDraftAnswers,
        [currentQuestion.question_idx]: input.trim(),
      };
      setExamDraftAnswers(updatedAnswers);
      setInput('');

      const answeredCount = Object.values(updatedAnswers).filter((a) => a.trim().length > 0).length;
      // Find next unanswered question (skip already-answered ones)
      let nextIdx = activeExamQuestionIdx;
      for (let i = activeExamQuestionIdx + 1; i < examQuestions.length; i++) {
        if (!(updatedAnswers[examQuestions[i].question_idx] || '').trim()) {
          nextIdx = i;
          break;
        }
      }
      // If no unanswered found after current, stay at end (all answered)
      if (nextIdx === activeExamQuestionIdx) {
        nextIdx = examQuestions.length; // signals "all done"
      }
      setActiveExamQuestionIdx(nextIdx);
      setExamProgress({
        current: Math.min(nextIdx + 1, examQuestions.length),
        total: examQuestions.length,
        answered: answeredCount,
      });
      return;
    }

    await sendMessage(input);
  };

  const handleSubmitAllExamAnswers = async () => {
    if (!sessionId || loading) return;

    // Only validate and submit questions not yet graded server-side
    const toSubmit = examQuestions.filter((q) => !examSubmittedIdxs.has(q.question_idx));

    const missing = toSubmit.filter((q) => !(examDraftAnswers[q.question_idx] || '').trim());
    if (missing.length > 0) {
      setActiveExamQuestionIdx(examQuestions.findIndex((q) => q.question_idx === missing[0].question_idx));
      return;
    }

    try {
      setLoading(true);
      setExamSubmitError(null);
      let finalResponse: any = null;
      let submitFailed = false;

      for (const q of toSubmit) {
        try {
          finalResponse = await submitStep(sessionId, (examDraftAnswers[q.question_idx] || '').trim());
          // Track successful submission so retries skip this question
          setExamSubmittedIdxs((prev) => new Set(prev).add(q.question_idx));
        } catch (err) {
          console.error(`Failed to submit answer for Q${q.question_idx + 1}:`, err);
          submitFailed = true;
          setExamSubmitError(`Failed to submit Q${q.question_idx + 1}. Please retry to submit remaining answers.`);
          // Stop on first failure so the student can retry remaining questions
          break;
        }
      }

      if (submitFailed || !finalResponse?.next_turn?.is_complete) return;

      setIsComplete(true);
      setMessages((prev) => [
        ...prev,
        {
          role: 'teacher',
          content: finalResponse.next_turn.message,
          hints: finalResponse.next_turn.hints,
        },
      ]);
      setExamProgress((prev) => prev ? { ...prev, answered: examQuestions.length, current: examQuestions.length } : prev);
      if (finalResponse.next_turn.exam_feedback) {
        setSummary({
          steps_completed: finalResponse.next_turn.exam_feedback.total,
          mastery_score: finalResponse.next_turn.exam_feedback.percentage / 100,
          misconceptions_seen: finalResponse.next_turn.exam_feedback.weak_areas || [],
          suggestions: finalResponse.next_turn.exam_feedback.next_steps || [],
        });
        setExamFeedback({
          score: finalResponse.next_turn.exam_feedback.score,
          total: finalResponse.next_turn.exam_feedback.total,
          percentage: finalResponse.next_turn.exam_feedback.percentage,
        });
      }
      setExamResults(finalResponse.next_turn.exam_results || []);
    } catch (error) {
      console.error('Failed to submit full exam:', error);
      setExamSubmitError('Something went wrong submitting the exam. Please try again.');
    } finally {
      setLoading(false);
    }
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

  const playTeacherAudio = async (text: string, slideId?: string) => {
    const version = ++audioPlayVersion.current;
    try {
      const audio = getOrCreateAudio();
      audio.pause();
      if (audio.src && audio.src.startsWith('blob:')) {
        URL.revokeObjectURL(audio.src);
      }

      const audioBlob = await synthesizeSpeech(text, audioLang);
      // Discard if a newer play request was made while we were fetching
      if (audioPlayVersion.current !== version) return;
      const url = URL.createObjectURL(audioBlob);
      audio.src = url;
      audio.onended = () => { setPlayingSlideId(null); URL.revokeObjectURL(url); };
      audio.onerror = () => { setPlayingSlideId(null); URL.revokeObjectURL(url); };
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

  const prefetchAudio = (text: string): Promise<Blob> => {
    const key = text;
    if (audioCacheRef.current.has(key)) return audioCacheRef.current.get(key)!;
    // Cap cache at 30 entries to limit memory on mobile devices
    if (audioCacheRef.current.size >= 30) {
      const oldest = audioCacheRef.current.keys().next().value;
      if (oldest !== undefined) audioCacheRef.current.delete(oldest);
    }
    const promise = synthesizeSpeech(text, audioLang).catch(err => {
      audioCacheRef.current.delete(key);
      throw err;
    });
    audioCacheRef.current.set(key, promise);
    return promise;
  };

  const playLineAudio = async (text: string): Promise<void> => {
    if (!text.trim()) return;
    const audio = getOrCreateAudio();
    audio.pause();
    if (audio.src && audio.src.startsWith('blob:')) URL.revokeObjectURL(audio.src);
    try {
      const blob = await prefetchAudio(text);
      const url = URL.createObjectURL(blob);
      audio.src = url;
      return new Promise<void>((resolve) => {
        let resolved = false;
        const done = () => {
          if (resolved) return;
          resolved = true;
          clearTimeout(safetyTimeout);
          audio.onended = null;
          audio.onerror = null;
          audio.onpause = null;
          audio.onstalled = null;
          setPlayingSlideId(null);
          URL.revokeObjectURL(url);
          resolve();
        };
        // Safety timeout: if audio doesn't finish within 30s, move on.
        // Prevents animation freeze when mobile browser audio session degrades.
        const safetyTimeout = setTimeout(() => {
          console.warn('playLineAudio: safety timeout — audio did not finish in 30s');
          done();
        }, 30_000);
        audio.onended = done;
        audio.onerror = done;
        // Catch silent stalls: browser may pause/stall audio after many plays
        audio.onpause = () => {
          // Only resolve if WE didn't pause it (i.e. no new playLineAudio call)
          if (audio.src === url) done();
        };
        audio.onstalled = () => {
          console.warn('playLineAudio: audio stalled');
          done();
        };
        audio.play()
          .then(() => setPlayingSlideId(carouselSlides[currentSlideIdx]?.id ?? null))
          .catch(() => done());
      });
    } catch (err) {
      console.error('Line TTS failed:', err);
    }
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

  const getContainerWidth = () => containerRef.current?.clientWidth || window.innerWidth;

  const handleFocusSwipeStart = (e: React.TouchEvent) => {
    focusSwipeStartX.current = e.touches[0].clientX;
    focusSwipeStartY.current = e.touches[0].clientY;
    focusSwipeDir.current = null;
    if (focusTrackRef.current) {
      focusTrackRef.current.style.transition = 'none';
    }
  };

  const handleFocusSwipeMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - focusSwipeStartX.current;
    const dy = e.touches[0].clientY - focusSwipeStartY.current;

    if (focusSwipeDir.current === null && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
      focusSwipeDir.current = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
    }

    if (focusSwipeDir.current === 'h') {
      const w = getContainerWidth();
      const pxOffset = -(Math.min(currentSlideIdx, carouselSlides.length - 1) * w) + dx;
      if (focusTrackRef.current) {
        focusTrackRef.current.style.transform = `translateX(${pxOffset}px)`;
      }
    }
  };

  const handleFocusSwipeEnd = (e: React.TouchEvent) => {
    let newIdx = currentSlideIdx;
    if (focusSwipeDir.current === 'h') {
      const dx = e.changedTouches[0].clientX - focusSwipeStartX.current;
      if (dx > 80 && currentSlideIdx > 0) {
        newIdx = currentSlideIdx - 1;
      } else if (dx < -80 && currentSlideIdx < carouselSlides.length - 1
          && !(carouselSlides[currentSlideIdx]?.type === 'check_in' && !completedCheckIns.has(carouselSlides[currentSlideIdx]?.id || ''))) {
        newIdx = currentSlideIdx + 1;
      }
      if (newIdx !== currentSlideIdx) {
        setCurrentSlideIdx(newIdx);
        // Persist position for card phase
        if (sessionPhase === 'card_phase' && sessionId) {
          localStorage.setItem(`slide-pos-${sessionId}`, String(newIdx));
          // Notify server of card position (skip welcome slide)
          if (newIdx > 0 && wsRef.current) {
            wsRef.current.sendJson({ type: 'card_navigate', payload: { card_idx: newIdx - 1 } });
          }
        }
      }
    }
    if (focusTrackRef.current) {
      focusTrackRef.current.style.transition = 'transform 0.3s ease-out';
      focusTrackRef.current.style.transform = `translateX(${-(newIdx * 100)}%)`;
    }
    focusSwipeDir.current = null;
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

  // ─── Practice CTA handlers ────────────────────────────────────────
  const handleStartPracticeFromCTA = async () => {
    if (!sessionId || !subject || !chapter || !topic) return;
    // guideline_id comes from the teach_me_complete response
    if (!teachMeGuidelineId) {
      setPracticeStartError('Could not determine topic for practice. Try again from topic selection.');
      return;
    }
    setCreatingPractice(true);
    setPracticeStartError(null);
    try {
      const response = await createSession({
        student: {
          id: studentId,
          grade,
          prefs: { style: 'standard', lang: 'en' },
        },
        goal: {
          chapter,
          syllabus: `${board}-G${grade}`,
          learning_objectives: [`Practice ${topic}`],
          guideline_id: teachMeGuidelineId,
        },
        mode: 'practice',
        source_session_id: sessionId,  // FR-10: explicit handoff
      });
      navigate(
        `/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}/practice/${response.session_id}`,
        { state: { firstTurn: response.first_turn, mode: 'practice' } },
      );
    } catch (err: any) {
      console.error('Failed to start practice:', err);
      setPracticeStartError(err?.message || 'Could not start practice session. Please try again.');
    } finally {
      setCreatingPractice(false);
    }
  };

  const handleDoneForNow = () => {
    if (!subject || !chapter || !topic) {
      navigate('/learn');
      return;
    }
    navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}`);
  };

  const handleEndPractice = async () => {
    if (!sessionId) return;
    if (!confirm("End this practice session? You'll see your progress.")) return;
    setEndingPractice(true);
    try {
      const result = await endPracticeSession(sessionId);
      setPracticeComplete(true);
      setIsComplete(true);
      setPracticeSummary(result.message);
      setPracticeQuestionsAnswered(result.questions_answered);
    } catch (err: any) {
      console.error('Failed to end practice:', err);
    } finally {
      setEndingPractice(false);
    }
  };

  const handleStartExamFromPractice = () => {
    if (!subject || !chapter || !topic) {
      navigate('/learn');
      return;
    }
    // Navigate back to mode-select so they can choose exam
    navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}`);
  };

  const handleSimplifyCard = async () => {
    if (!sessionId || simplifyLoading) return;
    const cardArrayIdx = currentSlideIdx - 1;
    if (cardArrayIdx < 0 || cardArrayIdx >= explanationCards.length) return;

    const currentCard = explanationCards[cardArrayIdx];
    const baseCardIdx = currentCard.source_card_idx ?? cardArrayIdx;

    setSimplifyLoading(true);
    try {
      const result = await simplifyCard(sessionId, baseCardIdx);

      if (result.action === 'insert_card' && result.card) {
        const newCard: ExplanationCard = {
          ...result.card,
          card_id: result.card_id,
          card_idx: baseCardIdx,
          source_card_idx: baseCardIdx,
        };
        setExplanationCards(prev => {
          const updated = [...prev];
          updated.splice(cardArrayIdx + 1, 0, newCard);
          return updated;
        });
        const newIdx = currentSlideIdx + 1;
        setCurrentSlideIdx(newIdx);
        if (sessionId) localStorage.setItem(`slide-pos-${sessionId}`, String(newIdx));
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

  return (
    <>
      <div className="app">
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
            {sessionId && sessionMode === 'practice' && !isComplete && (
              <button
                onClick={handleEndPractice}
                className="nav-action-btn"
                disabled={endingPractice}
                title="End this practice session"
                data-testid="end-practice-btn"
              >
                {endingPractice ? 'Ending...' : 'End Practice'}
              </button>
            )}
            {sessionId && sessionMode !== 'exam' && !isComplete && (
              <button
                onClick={() => setFeedbackModalOpen(true)}
                className="nav-action-btn feedback-btn"
                disabled={feedbackCount >= 3}
                title={feedbackCount >= 3 ? 'Feedback limit reached' : 'Share feedback'}
              >
                Feedback
              </button>
            )}
            {sessionId && sessionMode !== 'exam' && !isComplete && carouselSlides.length > 0 && (
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
                    playTeacherAudio(slide.audioText || slide.content, slide.id);
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
            {sessionMode === 'exam' && examProgress && (
              <>
                <span>Question {examProgress.current}/{examProgress.total}</span>
                <span>{examProgress.answered}/{examProgress.total} answered</span>
              </>
            )}
          </div>
        </div>

        <div className="chat-container" data-testid="chat-container">
          {teachMeComplete ? (
            <div className="summary-card" data-testid="teach-me-complete" style={{ flex: 1, overflowY: 'auto' }}>
              <h2>Nice work!</h2>
              {teachMeConceptsCovered.length > 0 && (
                <div className="summary-content">
                  <p>You've covered:</p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' }}>
                    {teachMeConceptsCovered.map((c, i) => (
                      <span key={i} style={{
                        display: 'inline-block',
                        background: '#dcfce7',
                        borderRadius: '12px',
                        padding: '4px 12px',
                        fontSize: '0.85rem',
                        color: '#166534',
                      }}>{c}</span>
                    ))}
                  </div>
                </div>
              )}
              {teachMeCompletionMessage && (
                <p style={{ marginTop: '16px', fontSize: '1rem', color: '#2d3748' }}>
                  {teachMeCompletionMessage}
                </p>
              )}
              {practiceStartError && (
                <p style={{ color: '#e53e3e', fontSize: '0.85rem', marginTop: '8px' }}>
                  {practiceStartError}
                </p>
              )}
              <button
                onClick={handleStartPracticeFromCTA}
                disabled={creatingPractice}
                className="restart-button"
                data-testid="start-practice-cta"
                style={{
                  marginTop: '20px',
                  fontSize: '1.1rem',
                  padding: '14px 24px',
                  fontWeight: 700,
                }}
              >
                {creatingPractice ? 'Setting up practice...' : "Let's Practice — put it to work!"}
              </button>
              <button
                onClick={handleDoneForNow}
                disabled={creatingPractice}
                className="restart-button"
                style={{
                  marginTop: '10px',
                  background: 'white',
                  color: '#667eea',
                  border: '2px solid #667eea',
                  fontSize: '0.9rem',
                }}
              >
                I'm done for now
              </button>
            </div>
          ) : practiceComplete ? (
            <div className="summary-card" data-testid="practice-complete" style={{ flex: 1, overflowY: 'auto' }}>
              <h2>Great practice session!</h2>
              {practiceSummary && (
                <p style={{ marginTop: '12px', fontSize: '1rem', color: '#2d3748' }}>
                  {practiceSummary}
                </p>
              )}
              {practiceQuestionsAnswered > 0 && (
                <p style={{ marginTop: '8px', fontSize: '0.85rem', color: '#718096' }}>
                  You answered {practiceQuestionsAnswered} question{practiceQuestionsAnswered === 1 ? '' : 's'}.
                </p>
              )}
              <button
                onClick={handleStartExamFromPractice}
                className="restart-button"
                data-testid="start-exam-cta"
                style={{
                  marginTop: '20px',
                  fontSize: '1.05rem',
                  padding: '14px 24px',
                  fontWeight: 700,
                }}
              >
                Make it official — take the exam
              </button>
              <button
                onClick={handleDoneForNow}
                className="restart-button"
                style={{
                  marginTop: '10px',
                  background: 'white',
                  color: '#667eea',
                  border: '2px solid #667eea',
                  fontSize: '0.9rem',
                }}
              >
                I'm done for now
              </button>
            </div>
          ) : showSummary ? (
            <div className="summary-card" data-testid="session-summary" style={{ flex: 1, overflowY: 'auto' }}>
              {sessionMode === 'clarify_doubts' ? (
                <>
                  <h2>Doubts Session Complete!</h2>
                  {conceptsDiscussed.length > 0 && (
                    <div className="summary-content">
                      <p><strong>Concepts Discussed:</strong></p>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' }}>
                        {conceptsDiscussed.map((c, i) => (
                          <span key={i} style={{
                            display: 'inline-block',
                            background: '#e2e8f0',
                            borderRadius: '12px',
                            padding: '4px 12px',
                            fontSize: '0.85rem',
                          }}>{c}</span>
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
                  {sessionMode === 'exam' && examFeedback ? (
                    <>
                      <h2>Exam Complete!</h2>
                      <div style={{ textAlign: 'center', margin: '12px 0 16px' }}>
                        <div style={{ fontSize: '2rem', fontWeight: 700, color: examFeedback.percentage >= 70 ? '#38a169' : examFeedback.percentage >= 40 ? '#dd6b20' : '#e53e3e' }}>
                          {examFeedback.score % 1 === 0 ? examFeedback.score.toFixed(0) : examFeedback.score.toFixed(1)}/{examFeedback.total}
                        </div>
                        <div style={{ fontSize: '0.9rem', color: '#718096' }}>{examFeedback.percentage.toFixed(1)}%</div>
                      </div>
                      {examResults.length > 0 && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
                          {examResults.map((r) => {
                            const scoreColor = (r.score ?? 0) >= 0.8 ? '#38a169' : (r.score ?? 0) >= 0.2 ? '#dd6b20' : '#e53e3e';
                            return (
                              <div key={r.question_idx} style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '12px', background: '#fafafa' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                  <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Q{r.question_idx + 1}</span>
                                  <span style={{ fontWeight: 700, color: scoreColor, fontSize: '0.9rem' }}>
                                    {r.score != null ? (r.score % 1 === 0 ? r.score.toFixed(0) : r.score.toFixed(1)) : '?'}/1
                                  </span>
                                </div>
                                <p style={{ fontSize: '0.85rem', color: '#2d3748', marginBottom: '6px' }}>{r.question_text}</p>
                                <div style={{ fontSize: '0.8rem', color: '#4a5568', marginBottom: '4px' }}>
                                  <strong>Your answer:</strong> {r.student_answer || '(no answer)'}
                                </div>
                                {r.expected_answer && (
                                  <div style={{ fontSize: '0.8rem', color: '#4a5568', marginBottom: '4px' }}>
                                    <strong>Expected:</strong> {r.expected_answer}
                                  </div>
                                )}
                                {r.marks_rationale && (
                                  <div style={{ fontSize: '0.8rem', color: '#718096', fontStyle: 'italic', borderTop: '1px solid #e2e8f0', paddingTop: '6px', marginTop: '6px' }}>
                                    {r.marks_rationale}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      {summary && summary.suggestions.length > 0 && (
                        <div style={{ marginBottom: '12px' }}>
                          <strong>Next Steps:</strong>
                          <ul>
                            {summary.suggestions.map((s, i) => (
                              <li key={i}>{s}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <h2>Well done!</h2>
                      {summary && summary.concepts_taught && summary.concepts_taught.length > 0 && (
                        <div className="summary-content">
                          <p>You covered:</p>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '4px' }}>
                            {summary.concepts_taught.map((c, i) => (
                              <span key={i} style={{
                                display: 'inline-block',
                                background: '#dcfce7',
                                borderRadius: '12px',
                                padding: '4px 12px',
                                fontSize: '0.85rem',
                                color: '#166534',
                              }}>{c}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  <button onClick={handleBack} className="restart-button">
                    Continue Practicing
                  </button>
                  <button
                    onClick={() => navigate(subject && chapter
                      ? `/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}`
                      : '/learn'
                    )}
                    className="restart-button"
                    style={{ marginTop: '10px', background: 'white', color: '#667eea', border: '2px solid #667eea' }}
                  >
                    Explore More Topics
                  </button>
                </>
              )}
            </div>
          ) : sessionMode === 'exam' ? (
            <>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                <button onClick={handleBack} className="back-button" style={{ fontSize: '0.8rem' }}>
                  ← Back
                </button>
              </div>
              {(() => {
                const allAnswered = examQuestions.length > 0 && examQuestions.every((q) => (examDraftAnswers[q.question_idx] || '').trim());
                return (
                <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
                  {examHydrationError && examQuestions.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '20px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
                      <p style={{ color: '#e53e3e', marginBottom: '12px' }}>Failed to load exam questions. Please try again.</p>
                      <button type="button" onClick={retryExamHydration} disabled={replayLoading} className="send-button">
                        {replayLoading ? 'Loading...' : 'Retry'}
                      </button>
                    </div>
                  ) : (
                  <>
                    {/* Answered questions list */}
                    {examQuestions.map((q, i) => {
                      const answer = (examDraftAnswers[q.question_idx] || '').trim();
                      const isActive = i === activeExamQuestionIdx && !allAnswered;

                      // Not yet revealed
                      if (!answer && !isActive) return null;

                      // Completed Q&A pair
                      if (answer && !isActive) return (
                        <div key={q.question_idx} style={{ background: '#f7fafc', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '12px 14px', marginBottom: '10px' }}>
                          <div style={{ fontWeight: 600, marginBottom: '6px' }}>Question {q.question_idx + 1}: <span style={{ fontWeight: 400 }}>{q.question_text}</span></div>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                            <span style={{ color: '#4a5568' }}>{answer}</span>
                            <button
                              type="button"
                              onClick={() => { setActiveExamQuestionIdx(i); setInput(answer); setExamDraftAnswers(prev => { const next = {...prev}; delete next[q.question_idx]; return next; }); }}
                              style={{ background: 'none', border: 'none', color: '#667eea', cursor: 'pointer', fontSize: '0.8rem', padding: 0, whiteSpace: 'nowrap' }}
                            >
                              Edit
                            </button>
                          </div>
                        </div>
                      );

                      // Active question with input
                      return (
                        <div key={q.question_idx} style={{ marginBottom: '10px' }}>
                          <div style={{ background: '#fff', border: '2px solid #667eea', borderRadius: '10px', padding: '12px 14px' }}>
                            <div style={{ fontWeight: 600, marginBottom: '10px' }}>Question {q.question_idx + 1}: <span style={{ fontWeight: 400 }}>{q.question_text}</span></div>
                            <form className={`input-form${isRecording ? ' recording' : ''}`} onSubmit={handleSubmit} style={{ margin: '0' }}>
                              <input
                                type="text"
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                placeholder={isRecording ? 'Listening...' : isTranscribing ? 'Transcribing...' : 'Type your answer...'}
                                disabled={loading || isTranscribing}
                                className="input-field"
                                data-testid="chat-input"
                                autoFocus
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
                              <button type="submit" disabled={loading || isTranscribing || !input.trim()} className="send-button" data-testid="send-button" aria-label={i < examQuestions.length - 1 ? 'Next' : 'Save'}>
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                  <line x1="12" y1="19" x2="12" y2="5" />
                                  <polyline points="5 12 12 5 19 12" />
                                </svg>
                              </button>
                            </form>
                          </div>
                        </div>
                      );
                    })}

                    {/* Submit button when all answered */}
                    {allAnswered && (
                      <div style={{ marginTop: '4px' }}>
                        {examSubmitError && (
                          <p style={{ color: '#e53e3e', fontSize: '0.85rem', marginBottom: '8px' }}>{examSubmitError}</p>
                        )}
                        <button
                          type="button"
                          onClick={handleSubmitAllExamAnswers}
                          disabled={loading}
                          className="send-button-wide"
                        >
                          {loading ? 'Submitting...' : 'Submit All Answers'}
                        </button>
                      </div>
                    )}
                    <div ref={examEndRef} />
                  </>
                  )}
                </div>
                );
              })()}
            </>
          ) : (
            /* Unified carousel for non-exam modes */
            <div className="focus-carousel" ref={containerRef}>
              <div
                className="focus-track-container"
                onTouchStart={handleFocusSwipeStart}
                onTouchMove={handleFocusSwipeMove}
                onTouchEnd={handleFocusSwipeEnd}
              >
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
                              onRevealComplete={() => setRevealedSlides(prev => new Set(prev).add(i))}
                              onBlockStart={(audioText) => {
                                if (audioText.trim()) prefetchAudio(audioText);
                              }}
                              onBlockTyped={async (audioText) => {
                                if (!audioText.trim()) return;
                                await playLineAudio(audioText);
                              }}
                            />
                          </div>
                          {revealedSlides.has(i) && slide.visual && (
                            <pre className="explanation-card-visual">{slide.visual}</pre>
                          )}
                          {revealedSlides.has(i) && slide.visualExplanation && (
                            <VisualExplanationComponent visual={slide.visualExplanation} />
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
                  /* User swiped back to a previous slide — show nav only */
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
                <div className="session-complete-card" style={{
                  margin: '16px',
                  padding: '20px',
                  background: '#f0fdf4',
                  borderRadius: '16px',
                  border: '1px solid #bbf7d0',
                  textAlign: 'center',
                }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: '#166534' }}>
                    Well done!
                  </h3>
                  {summary.concepts_taught && summary.concepts_taught.length > 0 && (
                    <div style={{ marginBottom: '16px' }}>
                      <p style={{ fontSize: '0.85rem', color: '#4a5568', margin: '0 0 8px' }}>You covered:</p>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', justifyContent: 'center' }}>
                        {summary.concepts_taught.map((c, i) => (
                          <span key={i} style={{
                            display: 'inline-block',
                            background: '#dcfce7',
                            borderRadius: '12px',
                            padding: '4px 12px',
                            fontSize: '0.82rem',
                            color: '#166534',
                          }}>{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  <p style={{ fontSize: '0.82rem', color: '#64748b', margin: '0 0 16px' }}>
                    What would you like to do next?
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <button
                      className="action-button primary"
                      onClick={handleBack}
                      style={{ width: '100%' }}
                    >
                      Continue Practicing
                    </button>
                    <button
                      className="action-button"
                      onClick={() => navigate(subject && chapter
                        ? `/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}`
                        : '/learn'
                      )}
                      style={{
                        width: '100%',
                        background: 'white',
                        color: '#667eea',
                        border: '2px solid #667eea',
                      }}
                    >
                      Explore More Topics
                    </button>
                  </div>
                </div>
              )}
              {isComplete && sessionMode !== 'teach_me' && (
                <div style={{ textAlign: 'center', padding: '16px' }}>
                  <button
                    className="action-button primary"
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
