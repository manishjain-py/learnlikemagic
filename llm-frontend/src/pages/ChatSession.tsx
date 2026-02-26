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
  const [examProgress, setExamProgress] = useState<{ current: number; total: number; correct: number } | null>(null);
  const [pauseSummaryData, setPauseSummaryData] = useState<PauseSummary | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);

  const subject = locState?.subject || '';
  const topic = locState?.topic || '';
  const subtopic = locState?.subtopic || '';

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => { scrollToBottom(); }, [messages]);

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
          if (state.current_step_idx != null) setStepIdx(state.current_step_idx);
          if (state.mode) setSessionMode(state.mode);
          if (state.is_complete) setIsComplete(true);
        })
        .catch((err) => console.error('Failed to load session:', err))
        .finally(() => setReplayLoading(false));
    }

    // Clear location state so refresh doesn't re-trigger
    navigate(`/session/${sessionId}`, { replace: true, state: null });
  }, [sessionId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !sessionId || loading) return;

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

      if (response.next_turn.is_complete) {
        setIsComplete(true);
        if (sessionMode !== 'clarify_doubts') {
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
                <span>{examProgress.correct}/{examProgress.current} correct</span>
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

          {!isComplete ? (
            <>
              <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                {sessionMode === 'teach_me' && (
                  <button onClick={handlePause} className="back-button" data-testid="pause-button" style={{ fontSize: '0.8rem' }}>
                    Pause Session
                  </button>
                )}
                {sessionMode === 'clarify_doubts' && (
                  <button onClick={() => setIsComplete(true)} className="back-button" style={{ fontSize: '0.8rem' }}>
                    End Session
                  </button>
                )}
                {sessionMode === 'exam' && (
                  <button onClick={handleEndExam} className="back-button" style={{ fontSize: '0.8rem' }}>
                    End Exam Early
                  </button>
                )}
              </div>
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
            </>
          ) : (
            <div className="summary-card" data-testid="session-summary">
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
