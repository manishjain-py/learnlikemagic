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
  Turn,
  SummaryResponse,
  VisualExplanation as VisualExplanationType,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';
import { useAuth } from '../contexts/AuthContext';
import DevToolsDrawer from '../features/devtools/components/DevToolsDrawer';
import VisualExplanationComponent from '../components/VisualExplanation';
import '../App.css';

interface Message {
  role: 'teacher' | 'student';
  content: string;
  audioText?: string | null;
  hints?: string[];
  visualExplanation?: VisualExplanationType | null;
}

interface ExamQuestionDraft {
  question_idx: number;
  question_text: string;
}

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
  const { grade } = useStudentProfile();
  const { user } = useAuth();
  const audioLang = user?.audio_language_preference || 'en';

  const locState = location.state as {
    firstTurn?: Turn;
    mode?: string;
    conversationHistory?: Array<{ role: string; content: string }>;
    currentStep?: number;
  } | null;

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [mastery, setMastery] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [showHints, setShowHints] = useState<number | null>(null);
  const [devToolsOpen, setDevToolsOpen] = useState(false);
  const [modelLabel, setModelLabel] = useState('');
  const [sessionMode, setSessionMode] = useState<'teach_me' | 'clarify_doubts' | 'exam'>(
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
  const [virtualTeacherOn, setVirtualTeacherOn] = useState(false);
  const [playingMsgIdx, setPlayingMsgIdx] = useState<number | null>(null);

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
  const isSpeaking = playingMsgIdx !== null;
  const [focusCardIdx, setFocusCardIdx] = useState<number | null>(null);
  const focusDismissedRef = useRef(false);
  const lastTapRef = useRef<{ idx: number; time: number }>({ idx: -1, time: 0 });
  const focusTrackRef = useRef<HTMLDivElement>(null);
  const focusSwipeStartX = useRef(0);
  const focusSwipeStartY = useRef(0);
  const focusSwipeDir = useRef<'h' | 'v' | null>(null);
  const prevFocusCardsLen = useRef(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const examEndRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // URL params from nested learn routes (preferred) — already decoded by React Router
  const subject = params.subject || '';
  const chapter = params.chapter || '';
  const topic = params.topic || '';

  // Derive focus carousel cards: each card = tutor message + optional student reply
  const focusCards = useMemo(() => {
    const cards: { tutorMsg: Message; tutorIdx: number; studentMsg: Message | null }[] = [];
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].role === 'teacher') {
        const next = (i + 1 < messages.length && messages[i + 1].role === 'student')
          ? messages[i + 1] : null;
        cards.push({ tutorMsg: messages[i], tutorIdx: i, studentMsg: next });
      }
    }
    return cards;
  }, [messages]);

  // Auto-advance carousel when new cards appear
  useEffect(() => {
    if (focusCardIdx === null || focusDismissedRef.current) return;
    const prev = prevFocusCardsLen.current;
    prevFocusCardsLen.current = focusCards.length;
    if (focusCards.length > prev && prev > 0) {
      // Only auto-advance if user was on the last card
      if (focusCardIdx === prev - 1) {
        setFocusCardIdx(focusCards.length - 1);
        // Auto-play TTS for new card
        const newCard = focusCards[focusCards.length - 1];
        if (newCard && (user?.focus_mode !== false) && !virtualTeacherOn) {
          playTeacherAudio(newCard.tutorMsg.audioText || newCard.tutorMsg.content, newCard.tutorIdx);
        }
      }
    }
  }, [focusCards.length]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

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

  useEffect(() => { scrollToBottom(); }, [messages]);
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
      setMessages([{
        role: 'teacher',
        content: locState.firstTurn.message,
        audioText: locState.firstTurn.audio_text,
        hints: locState.firstTurn.hints,
        visualExplanation: locState.firstTurn.visual_explanation,
      }]);
      setStepIdx(locState.firstTurn.step_idx);
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

      // Auto-play first turn in virtual teacher mode
      if (virtualTeacherOn && locState.firstTurn.message) {
        playTeacherAudio(locState.firstTurn.audio_text || locState.firstTurn.message);
      }
      // Auto-open focus carousel on first turn
      if ((user?.focus_mode !== false) && !virtualTeacherOn) {
        setFocusCardIdx(0);
        prevFocusCardsLen.current = 1;
        focusDismissedRef.current = false;
        playTeacherAudio(locState.firstTurn.audio_text || locState.firstTurn.message, 0);
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

          // Hydrate completion for all modes
          const completed = state.clarify_complete
            || state.exam_finished
            || (state.topic && state.current_step > (state.topic?.study_plan?.steps?.length ?? Infinity));
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

    const userMessage = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'student', content: userMessage }]);
    setLoading(true);

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
        },
      ]);
      setStepIdx(response.next_turn.step_idx);
      setMastery(response.next_turn.mastery_score);

      // Auto-play TTS in virtual teacher mode
      if (virtualTeacherOn && response.next_turn.message) {
        playTeacherAudio(response.next_turn.audio_text || response.next_turn.message);
      }

      // Focus carousel auto-advance is handled by the useEffect watching focusCards.length

      // Update concepts discussed for clarify_doubts mode
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
        } else if (sessionMode !== 'clarify_doubts') {
          const summaryData = await getSummary(sessionId);
          setSummary(summaryData);
        }
      }
    } catch (error) {
      console.error('Failed to submit answer:', error);
    } finally {
      setLoading(false);
    }
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

  const toggleHints = (index: number) => {
    setShowHints(showHints === index ? null : index);
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

  // Create a persistent Audio element once to satisfy browser autoplay policy.
  // Browsers allow .play() on an element that the user has already interacted with.
  const getOrCreateAudio = (): HTMLAudioElement => {
    if (!audioRef.current) {
      audioRef.current = new Audio();
    }
    return audioRef.current;
  };

  const playTeacherAudio = async (text: string, msgIdx?: number) => {
    try {
      const audio = getOrCreateAudio();
      // Stop any currently playing audio
      audio.pause();
      if (audio.src && audio.src.startsWith('blob:')) {
        URL.revokeObjectURL(audio.src);
      }

      const audioBlob = await synthesizeSpeech(text, audioLang);
      const url = URL.createObjectURL(audioBlob);
      audio.src = url;
      audio.onended = () => { setPlayingMsgIdx(null); URL.revokeObjectURL(url); };
      audio.onerror = () => { setPlayingMsgIdx(null); URL.revokeObjectURL(url); };
      await audio.play();
      setPlayingMsgIdx(msgIdx ?? -1);
    } catch (err) {
      console.error('TTS playback failed:', err);
      setPlayingMsgIdx(null);
    }
  };

  const stopAudio = () => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      if (audio.src && audio.src.startsWith('blob:')) {
        URL.revokeObjectURL(audio.src);
      }
      audio.src = '';
    }
    setPlayingMsgIdx(null);
  };

  const handleTeacherDoubleTap = (idx: number) => {
    const now = Date.now();
    if (lastTapRef.current.idx === idx && now - lastTapRef.current.time < 300) {
      const cardIdx = focusCards.findIndex((c) => c.tutorIdx === idx);
      if (cardIdx >= 0) {
        setFocusCardIdx(cardIdx);
        focusDismissedRef.current = false;
        prevFocusCardsLen.current = focusCards.length;
        if ((user?.focus_mode !== false) && messages[idx]) {
          playTeacherAudio(messages[idx].audioText || messages[idx].content, idx);
        }
      }
      lastTapRef.current = { idx: -1, time: 0 };
    } else {
      lastTapRef.current = { idx, time: now };
    }
  };

  const closeFocusCard = () => {
    setFocusCardIdx(null);
    focusDismissedRef.current = true;
    stopAudio();
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

    if (focusSwipeDir.current === 'h' && focusCardIdx !== null) {
      const baseOffset = -(focusCardIdx * window.innerWidth);
      if (focusTrackRef.current) {
        focusTrackRef.current.style.transform = `translateX(${baseOffset + dx}px)`;
      }
    }
  };

  const handleFocusSwipeEnd = (e: React.TouchEvent) => {
    let newIdx = focusCardIdx;
    if (focusSwipeDir.current === 'h' && focusCardIdx !== null) {
      const dx = e.changedTouches[0].clientX - focusSwipeStartX.current;
      if (dx > 80 && focusCardIdx > 0) {
        newIdx = focusCardIdx - 1;
      } else if (dx < -80 && focusCardIdx < focusCards.length - 1) {
        newIdx = focusCardIdx + 1;
      }
      if (newIdx !== focusCardIdx) setFocusCardIdx(newIdx);
    }
    if (focusTrackRef.current && newIdx !== null) {
      focusTrackRef.current.style.transition = 'transform 0.3s ease-out';
      focusTrackRef.current.style.transform = `translateX(${-(newIdx * window.innerWidth)}px)`;
    }
    focusSwipeDir.current = null;
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
            {sessionId && sessionMode !== 'exam' && (
              <button
                onClick={() => {
                  const next = !virtualTeacherOn;
                  setVirtualTeacherOn(next);
                  if (next) {
                    const audio = getOrCreateAudio();
                    audio.play().catch(() => {});
                    audio.pause();
                    const lastTeacher = messages.filter((m) => m.role === 'teacher').slice(-1)[0];
                    if (lastTeacher?.content) {
                      playTeacherAudio(lastTeacher.audioText || lastTeacher.content);
                    }
                  } else if (audioRef.current) {
                    audioRef.current.pause();
                    audioRef.current = null;
                    setPlayingMsgIdx(null);
                  }
                }}
                className="nav-action-btn"
                title={virtualTeacherOn ? 'Text Mode' : 'Virtual Teacher'}
              >
                {virtualTeacherOn ? 'Text' : 'VT'}
              </button>
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
            {sessionMode === 'teach_me' && (
              <>
                <span>Step {stepIdx}/10</span>
                <span>Coverage: {coverage.toFixed(0)}%</span>
              </>
            )}
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
          {sessionMode === 'teach_me' && (
            <>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${(stepIdx / 10) * 100}%` }} />
              </div>
              <div className="mastery-track">
                <div className="mastery-fill" style={{ width: `${coverage}%` }} />
              </div>
            </>
          )}
        </div>

        <div className="chat-container" data-testid="chat-container">
          {sessionMode !== 'exam' && virtualTeacherOn && !isComplete ? (
            <div className="virtual-teacher-view">
              {/* Close button */}
              <button
                className="vt-close-btn"
                onClick={() => {
                  setVirtualTeacherOn(false);
                  stopAudio();
                }}
                aria-label="Exit virtual teacher"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>

              {/* Avatar area */}
              <div className="vt-avatar-area">
                <img
                  src={isSpeaking ? '/teacher-avatar.gif' : '/teacher-avatar-still.gif'}
                  alt="Virtual Teacher"
                  className={`teacher-gif${isSpeaking ? ' speaking' : ''}`}
                />
                {/* Subtitle overlay */}
                {messages.length > 0 && (() => {
                  const lastTeacherMsg = messages.filter((m) => m.role === 'teacher').slice(-1)[0]?.content || '';
                  return lastTeacherMsg ? (
                    <div className="teacher-subtitle">
                      <ReactMarkdown>{lastTeacherMsg}</ReactMarkdown>
                    </div>
                  ) : null;
                })()}
              </div>

              {/* Typing indicator or input area */}
              {loading ? (
                <div className="vt-typing-indicator">
                  <div className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              ) : !isSpeaking ? (
                <div className="vt-input-area">
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
              ) : null}
            </div>
          ) : sessionMode !== 'exam' ? (
          <div className="messages">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`message ${msg.role}`}
                {...(msg.role === 'teacher' ? { 'data-testid': 'teacher-message', onClick: () => handleTeacherDoubleTap(idx) } : {})}
              >
                <div className="message-content">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
                {msg.role === 'teacher' && msg.visualExplanation && (
                  <VisualExplanationComponent visual={msg.visualExplanation} />
                )}
                {msg.role === 'teacher' && (
                  <button
                    className={`audio-play-btn${playingMsgIdx === idx ? ' playing' : ''}`}
                    onClick={() => {
                      if (playingMsgIdx === idx) {
                        stopAudio();
                      } else {
                        playTeacherAudio(msg.audioText || msg.content, idx);
                      }
                    }}
                    title={playingMsgIdx === idx ? 'Stop audio' : 'Play audio'}
                    aria-label={playingMsgIdx === idx ? 'Stop audio' : 'Play audio'}
                  >
                    {playingMsgIdx === idx ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /></svg>
                    )}
                  </button>
                )}
                {msg.hints && msg.hints.length > 0 && (
                  <div className="hints-container">
                    <button
                      className="hints-toggle"
                      onClick={() => toggleHints(idx)}
                    >
                      {showHints === idx ? '\u25BC' : '\u25B6'} Hints
                    </button>
                    {showHints === idx && (
                      <ul className="hints">
                        {msg.hints.map((hint, hintIdx) => (
                          <li key={hintIdx}>{hint}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="message teacher loading">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          ) : null}

          {sessionMode !== 'exam' && virtualTeacherOn && !isComplete ? null : !isComplete ? (
            <>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                <button onClick={handleBack} className="back-button" style={{ fontSize: '0.8rem' }}>
                  ← Back
                </button>
              </div>
              {sessionMode === 'exam' ? (() => {
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
              })() : (
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
              )}
            </>
          ) : (
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
                      <h2>Session Complete!</h2>
                      {summary && (
                        <div className="summary-content">
                          <p>
                            <strong>Steps Completed:</strong> {summary.steps_completed}
                          </p>
                          <p>
                            <strong>Final Mastery:</strong>{' '}
                            {(summary.mastery_score * 100).toFixed(0)}%
                          </p>
                          {summary.misconceptions_seen.length > 0 && (
                            <div>
                              <strong>Areas to Review:</strong>
                              <ul>
                                {summary.misconceptions_seen.map((m, i) => (
                                  <li key={i}>{m}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          <div>
                            <strong>Next Steps:</strong>
                            <ul>
                              {summary.suggestions.map((s, i) => (
                                <li key={i}>{s}</li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  <button onClick={handleBack} className="restart-button">
                    Back to Topic
                  </button>
                  <button
                    onClick={() => navigate('/report-card')}
                    className="restart-button"
                    style={{ marginTop: '10px', background: 'white', color: '#667eea', border: '2px solid #667eea' }}
                  >
                    View Report Card
                  </button>
                </>
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

      {/* Focus Carousel */}
      {focusCardIdx !== null && focusCards.length > 0 && sessionMode !== 'exam' && !virtualTeacherOn && !isComplete && (
        <div className="focus-carousel">
          <div className="focus-header">
            <button className="focus-exit-btn" onClick={closeFocusCard} aria-label="Exit focus mode">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
            {(subject || chapter || topic) && (
              <span className="focus-breadcrumb">
                {subject && <>{subject}</>}
                {chapter && <> &rsaquo; {chapter}</>}
                {topic && <> &rsaquo; {topic}</>}
              </span>
            )}
            <div className="focus-header-right">
              <button
                className={`focus-audio-btn${playingMsgIdx === focusCards[focusCardIdx]?.tutorIdx ? ' playing' : ''}`}
                onClick={() => {
                  const card = focusCards[focusCardIdx!];
                  if (!card) return;
                  if (playingMsgIdx === card.tutorIdx) {
                    stopAudio();
                  } else {
                    playTeacherAudio(card.tutorMsg.audioText || card.tutorMsg.content, card.tutorIdx);
                  }
                }}
                aria-label={playingMsgIdx === focusCards[focusCardIdx]?.tutorIdx ? 'Stop audio' : 'Play audio'}
              >
                {playingMsgIdx === focusCards[focusCardIdx]?.tutorIdx ? (
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
              <span className="focus-counter">{(focusCardIdx ?? 0) + 1}/{focusCards.length}</span>
            </div>
          </div>
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
                transform: `translateX(${-(focusCardIdx * window.innerWidth)}px)`,
                transition: 'transform 0.3s ease-out',
              }}
            >
              {focusCards.map((card, ci) => (
                <div key={ci} className="focus-slide">
                  <div className="focus-tutor-msg">
                    <ReactMarkdown>{card.tutorMsg.content}</ReactMarkdown>
                  </div>
                  {card.studentMsg && (
                    <div className="focus-student-msg">
                      <div className="focus-student-label">You</div>
                      {card.studentMsg.content}
                    </div>
                  )}
                  {ci === focusCards.length - 1 && loading && (
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
          {focusCardIdx === focusCards.length - 1 && !loading && !isComplete && (
            <div className="focus-input-area">
              <form className={`input-form${isRecording ? ' recording' : ''}`} onSubmit={handleSubmit}>
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={isRecording ? 'Listening...' : isTranscribing ? 'Transcribing...' : 'Type your answer...'}
                  disabled={loading || isTranscribing}
                  className="input-field"
                />
                <button
                  type="button"
                  onClick={toggleRecording}
                  disabled={loading || isTranscribing}
                  className={`mic-button${isRecording ? ' recording' : ''}${isTranscribing ? ' transcribing' : ''}`}
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
                <button type="submit" disabled={loading || isTranscribing || !input.trim()} className="send-button" aria-label="Send">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
              </form>
            </div>
          )}
        </div>
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
