import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, useLocation, useOutletContext } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  submitStep,
  getSummary,
  getModelConfig,
  getSessionReplay,
  transcribeAudio,
  pauseSession,
  endExamEarly,
  endClarifySession,
  Turn,
  SummaryResponse,
  PauseSummary,
} from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';
import DevToolsDrawer from '../features/devtools/components/DevToolsDrawer';
import '../App.css';

interface Message {
  role: 'teacher' | 'student';
  content: string;
  hints?: string[];
}

interface ExamQuestionDraft {
  question_idx: number;
  question_text: string;
}

export default function ChatSession() {
  const navigate = useNavigate();
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const { grade } = useStudentProfile();

  const locState = location.state as {
    firstTurn?: Turn;
    mode?: string;
    subject?: string;
    topic?: string;
    subtopic?: string;
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
  const [examResults, setExamResults] = useState<Array<{ question_idx: number; question_text: string; student_answer?: string | null; result?: 'correct' | 'partial' | 'incorrect' | null }>>([]);
  const [examQuestions, setExamQuestions] = useState<ExamQuestionDraft[]>([]);
  const [examDraftAnswers, setExamDraftAnswers] = useState<Record<number, string>>({});
  const [activeExamQuestionIdx, setActiveExamQuestionIdx] = useState(0);
  const [examSubmittedIdxs, setExamSubmittedIdxs] = useState<Set<number>>(new Set());
  const [pauseSummaryData, setPauseSummaryData] = useState<PauseSummary | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [examHydrationError, setExamHydrationError] = useState(false);
  const [examSubmitError, setExamSubmitError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const examEndRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);

  const subject = locState?.subject || '';
  const topic = locState?.topic || '';
  const subtopic = locState?.subtopic || '';

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
        hints: locState.firstTurn.hints,
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
    } else if (locState?.conversationHistory) {
      // Resumed session
      setMessages(
        locState.conversationHistory.map((m) => ({
          role: m.role === 'student' ? 'student' as const : 'teacher' as const,
          content: m.content,
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
    navigate(`/session/${sessionId}`, { replace: true, state: null });
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
          hints: response.next_turn.hints,
        },
      ]);
      setStepIdx(response.next_turn.step_idx);
      setMastery(response.next_turn.mastery_score);

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

  const handlePause = async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const result = await pauseSession(sessionId);
      setPauseSummaryData(result);
      setIsComplete(true);
    } catch (error) {
      console.error('Failed to pause session:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleEndClarify = async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const result = await endClarifySession(sessionId);
      if (result.concepts_discussed) {
        setConceptsDiscussed(result.concepts_discussed);
      }
      setIsComplete(true);
    } catch (error) {
      console.error('Failed to end clarify session:', error);
      // Fallback: still mark complete locally so user isn't stuck
      setIsComplete(true);
    } finally {
      setLoading(false);
    }
  };

  const handleEndExam = async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const result = await endExamEarly(sessionId);
      setIsComplete(true);
      setSummary({
        steps_completed: result.total,
        mastery_score: result.percentage / 100,
        misconceptions_seen: result.feedback?.weak_areas || [],
        suggestions: result.feedback?.next_steps || [],
      });
    } catch (error) {
      console.error('Failed to end exam:', error);
    } finally {
      setLoading(false);
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
        <header className="header" style={{ position: 'relative' }}>
          <h1>Learn Like Magic</h1>
          <p className="subtitle">
            Grade {grade}{subject && ` \u2022 ${subject}`}{topic && ` \u2022 ${topic}`}{subtopic && ` \u2022 ${subtopic}`}
            {modelLabel && (
              <span style={{
                marginLeft: '8px',
                padding: '2px 8px',
                background: 'rgba(255,255,255,0.15)',
                borderRadius: '10px',
                fontSize: '0.7rem',
                fontWeight: 500,
                letterSpacing: '0.02em',
              }}>
                ⚡ {modelLabel}
              </span>
            )}
          </p>
          {sessionId && (
            <button
              onClick={() => setDevToolsOpen(true)}
              style={{
                position: 'absolute',
                top: '12px',
                right: '12px',
                padding: '4px 10px',
                background: 'rgba(255,255,255,0.2)',
                color: 'white',
                border: '1px solid rgba(255,255,255,0.4)',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              Dev Tools
            </button>
          )}
        </header>

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
          {sessionMode !== 'exam' && (
          <div className="messages">
            {messages.map((msg, idx) => (
              <div key={idx} className={`message ${msg.role}`} {...(msg.role === 'teacher' ? { 'data-testid': 'teacher-message' } : {})}>
                <div className="message-content">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
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
          )}

          {!isComplete ? (
            <>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                {sessionMode === 'teach_me' && (
                  <button onClick={handlePause} className="back-button" data-testid="pause-button" style={{ fontSize: '0.8rem' }}>
                    Pause Session
                  </button>
                )}
                {sessionMode === 'clarify_doubts' && (
                  <button onClick={handleEndClarify} className="back-button" style={{ fontSize: '0.8rem' }}>
                    End Session
                  </button>
                )}
                {sessionMode === 'exam' && (
                  <button onClick={handleEndExam} className="back-button" style={{ fontSize: '0.8rem' }}>
                    End Exam Early
                  </button>
                )}
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
                              onClick={() => { setActiveExamQuestionIdx(i); setInput(answer); }}
                              style={{ background: 'none', border: 'none', color: '#667eea', cursor: 'pointer', fontSize: '0.8rem', padding: 0, whiteSpace: 'nowrap' }}
                            >
                              Edit
                            </button>
                          </div>
                        </div>
                      );

                      // Active question with input
                      return (
                        <div key={q.question_idx} style={{ background: '#fff', border: '2px solid #667eea', borderRadius: '10px', padding: '12px 14px', marginBottom: '10px' }}>
                          <div style={{ fontWeight: 600, marginBottom: '10px' }}>Question {q.question_idx + 1}: <span style={{ fontWeight: 400 }}>{q.question_text}</span></div>
                          <form className="input-form" onSubmit={handleSubmit}>
                            <input
                              type="text"
                              value={input}
                              onChange={(e) => setInput(e.target.value)}
                              placeholder={isRecording ? 'Listening...' : isTranscribing ? 'Transcribing...' : 'Type your answer...'}
                              disabled={loading || isTranscribing}
                              className={`input-field${isRecording ? ' recording' : ''}`}
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
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <circle cx="12" cy="12" r="10" />
                                  <path d="M12 6v6l4 2" />
                                </svg>
                              ) : (
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                                  <line x1="12" y1="19" x2="12" y2="23" />
                                  <line x1="8" y1="23" x2="16" y2="23" />
                                </svg>
                              )}
                            </button>
                            <button type="submit" disabled={loading || isTranscribing || !input.trim()} className="send-button" data-testid="send-button">
                              {i < examQuestions.length - 1 ? 'Next' : 'Save'}
                            </button>
                          </form>
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
                          className="send-button"
                          style={{ width: '100%', padding: '12px', fontSize: '1rem' }}
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
                <form className="input-form" onSubmit={handleSubmit}>
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder={isRecording ? 'Listening...' : isTranscribing ? 'Transcribing...' : 'Type your answer...'}
                    disabled={loading || isTranscribing}
                    className={`input-field${isRecording ? ' recording' : ''}`}
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
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 6v6l4 2" />
                      </svg>
                    ) : (
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                        <line x1="12" y1="19" x2="12" y2="23" />
                        <line x1="8" y1="23" x2="16" y2="23" />
                      </svg>
                    )}
                  </button>
                  <button type="submit" disabled={loading || isTranscribing || !input.trim()} className="send-button" data-testid="send-button">
                    Send
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
                  <button onClick={() => navigate('/learn')} className="restart-button">
                    Start New Session
                  </button>
                </>
              ) : (
                <>
                  <h2>Session Complete!</h2>
                  {summary && (
                    <div className="summary-content">
                      <p>
                        <strong>Steps Completed:</strong> {summary.steps_completed}
                      </p>
                      {sessionMode === 'exam' && examFeedback ? (
                        <p>
                          <strong>Final Exam Score:</strong>{' '}
                          {examFeedback.score}/{examFeedback.total} ({examFeedback.percentage.toFixed(1)}%)
                        </p>
                      ) : (
                        <p>
                          <strong>Final Mastery:</strong>{' '}
                          {(summary.mastery_score * 100).toFixed(0)}%
                        </p>
                      )}
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
                      {sessionMode === 'exam' && examResults.length > 0 && (
                        <div>
                          <strong>Question Review:</strong>
                          <ul>
                            {examResults.map((r) => (
                              <li key={r.question_idx}>
                                Q{r.question_idx + 1}: {r.result === 'correct' ? '✅ Correct' : r.result === 'partial' ? '🟨 Partial' : '❌ Incorrect'}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                  <button onClick={() => navigate('/learn')} className="restart-button">
                    Start New Session
                  </button>
                  <button
                    onClick={() => navigate('/scorecard')}
                    className="restart-button"
                    style={{ marginTop: '10px', background: 'white', color: '#667eea', border: '2px solid #667eea' }}
                  >
                    View Scorecard
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
    </>
  );
}
