import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import ModeSelection from './components/ModeSelection';
import {
  createSession,
  submitStep,
  getSummary,
  getCurriculum,
  getModelConfig,
  getSubtopicProgress,
  transcribeAudio,
  pauseSession,
  resumeSession as resumeSessionAPI,
  endExamEarly,
  Turn,
  SummaryResponse,
  SubtopicInfo,
  SubtopicProgress,
  ResumableSession,
  PauseSummary,
} from './api';
import { useAuth } from './contexts/AuthContext';
import DevToolsDrawer from './features/devtools/components/DevToolsDrawer';
import './App.css';

interface Message {
  role: 'teacher' | 'student';
  content: string;
  hints?: string[];
}

function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Selection state
  const [selectionStep, setSelectionStep] = useState<
    'subject' | 'topic' | 'subtopic' | 'mode' | 'chat'
  >('subject');
  const [subjects, setSubjects] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [subtopics, setSubtopics] = useState<SubtopicInfo[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<string | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);
  const [selectedSubtopic, setSelectedSubtopic] = useState<SubtopicInfo | null>(null);

  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [mastery, setMastery] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [showHints, setShowHints] = useState<number | null>(null);
  const [devToolsOpen, setDevToolsOpen] = useState(false);
  const [modelLabel, setModelLabel] = useState<string>('');
  const [subtopicProgress, setSubtopicProgress] = useState<Record<string, SubtopicProgress>>({});
  const [sessionMode, setSessionMode] = useState<'teach_me' | 'clarify_doubts' | 'exam'>('teach_me');
  const [coverage, setCoverage] = useState(0);
  const [conceptsDiscussed, setConceptsDiscussed] = useState<string[]>([]);
  const [examProgress, setExamProgress] = useState<{ current: number; total: number; correct: number } | null>(null);
  const [pauseSummaryData, setPauseSummaryData] = useState<PauseSummary | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Student profile from authenticated user (replaces hardcoded values)
  const COUNTRY = 'India';
  const BOARD = user?.board || 'CBSE';
  const GRADE = user?.grade || 3;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Fetch subjects and model config on mount
  useEffect(() => {
    fetchSubjects();
    getModelConfig()
      .then((config) => setModelLabel(config.tutor?.description || config.tutor?.model_id || ''))
      .catch(() => setModelLabel(''));
  }, []);

  // Handle incoming session from "Practice Again" (scorecard navigation)
  useEffect(() => {
    const state = location.state as { sessionId?: string; firstTurn?: Turn } | null;
    if (state?.sessionId && state?.firstTurn) {
      setSessionId(state.sessionId);
      setMessages([{
        role: 'teacher',
        content: state.firstTurn.message,
        hints: state.firstTurn.hints,
      }]);
      setStepIdx(state.firstTurn.step_idx);
      setMastery(state.firstTurn.mastery_score);
      setSelectionStep('chat');
      // Clear location state so a page refresh doesn't re-trigger
      navigate('/', { replace: true, state: null });
    }
  }, []);

  const fetchSubjects = async () => {
    setLoading(true);
    try {
      const response = await getCurriculum({
        country: COUNTRY,
        board: BOARD,
        grade: GRADE,
      });
      setSubjects(response.subjects || []);
    } catch (error) {
      console.error('Failed to fetch subjects:', error);
      alert('Failed to load subjects. Please refresh the page.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubjectSelect = async (subject: string) => {
    setSelectedSubject(subject);
    setLoading(true);
    try {
      const response = await getCurriculum({
        country: COUNTRY,
        board: BOARD,
        grade: GRADE,
        subject,
      });
      setTopics(response.topics || []);
      setSelectionStep('topic');
    } catch (error) {
      console.error('Failed to fetch topics:', error);
      alert('Failed to load topics.');
    } finally {
      setLoading(false);
    }
  };

  const handleTopicSelect = async (topic: string) => {
    setSelectedTopic(topic);
    setLoading(true);
    try {
      const response = await getCurriculum({
        country: COUNTRY,
        board: BOARD,
        grade: GRADE,
        subject: selectedSubject!,
        topic,
      });
      setSubtopics(response.subtopics || []);
      setSelectionStep('subtopic');
      // Fetch user progress for coverage indicators
      getSubtopicProgress().then(setSubtopicProgress).catch(() => {});
    } catch (error) {
      console.error('Failed to fetch subtopics:', error);
      alert('Failed to load subtopics.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubtopicSelect = async (subtopic: SubtopicInfo) => {
    setSelectedSubtopic(subtopic);
    setSelectionStep('mode');
  };

  const handleModeSelect = async (mode: 'teach_me' | 'clarify_doubts' | 'exam') => {
    setSessionMode(mode);
    await startSession(selectedSubtopic!, mode);
  };

  const handleResume = async (resumeSessionId: string) => {
    setSessionMode('teach_me');
    try {
      setLoading(true);
      const result = await resumeSessionAPI(resumeSessionId);
      setSessionId(resumeSessionId);
      // Populate conversation history so chat isn't blank
      if (result.conversation_history && result.conversation_history.length > 0) {
        setMessages(
          result.conversation_history.map((m: { role: string; content: string }) => ({
            role: m.role === 'student' ? 'student' as const : 'teacher' as const,
            content: m.content,
          }))
        );
      }
      if (result.current_step) {
        setStepIdx(result.current_step);
      }
      setSelectionStep('chat');
    } catch (error) {
      console.error('Failed to resume session:', error);
      alert('Failed to resume session. Please try again.');
    } finally {
      setLoading(false);
    }
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
      alert('Failed to pause session.');
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
      alert('Failed to end exam.');
    } finally {
      setLoading(false);
    }
  };

  const startSession = async (subtopic: SubtopicInfo, mode: 'teach_me' | 'clarify_doubts' | 'exam' = 'teach_me') => {
    setLoading(true);
    try {
      const response = await createSession({
        student: {
          id: user?.id || 's1',
          grade: GRADE,
          prefs: { style: 'standard', lang: 'en' },
        },
        goal: {
          topic: selectedTopic!,
          syllabus: `${BOARD}-G${GRADE}`,
          learning_objectives: [`Learn ${subtopic.subtopic}`],
          guideline_id: subtopic.guideline_id,
        },
        mode,
      });

      setSessionId(response.session_id);
      setMessages([
        {
          role: 'teacher',
          content: response.first_turn.message,
          hints: response.first_turn.hints,
        },
      ]);
      setStepIdx(response.first_turn.step_idx);
      setMastery(response.first_turn.mastery_score);
      setSelectionStep('chat');
    } catch (error) {
      console.error('Failed to start session:', error);
      alert('Failed to start session. Please try again.');
    } finally {
      setLoading(false);
    }
  };

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

      if (response.next_turn.is_complete) {
        setIsComplete(true);
        const summaryData = await getSummary(sessionId);
        setSummary(summaryData);
      }
    } catch (error) {
      console.error('Failed to submit answer:', error);
      alert('Failed to submit answer. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const toggleHints = (index: number) => {
    setShowHints(showHints === index ? null : index);
  };

  const toggleRecording = async () => {
    if (isRecording) {
      // Stop recording — onstop callback handles transcription
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Pick a supported MIME type; fall back to browser default
      const preferredTypes = ['audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t));
      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const activeMime = mediaRecorder.mimeType || 'audio/webm';

      audioChunksRef.current = [];
      const baseInput = input; // snapshot before recording starts

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        // Stop all mic tracks so the browser indicator goes away
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

  const handleBack = () => {
    if (selectionStep === 'topic') {
      setSelectionStep('subject');
      setSelectedSubject(null);
    } else if (selectionStep === 'subtopic') {
      setSelectionStep('topic');
      setSelectedTopic(null);
    } else if (selectionStep === 'mode') {
      setSelectionStep('subtopic');
      setSelectedSubtopic(null);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  // User menu component
  const UserMenu = () => (
    <div style={{ position: 'absolute', top: '12px', right: '12px' }}>
      <button
        onClick={() => setShowUserMenu(!showUserMenu)}
        style={{
          padding: '6px 12px',
          background: 'rgba(255,255,255,0.2)',
          color: 'white',
          border: '1px solid rgba(255,255,255,0.4)',
          borderRadius: '20px',
          fontSize: '0.8rem',
          fontWeight: 500,
          cursor: 'pointer',
        }}
      >
        {user?.name || 'Menu'}
      </button>
      {showUserMenu && (
        <div style={{
          position: 'absolute',
          top: '40px',
          right: 0,
          background: 'white',
          borderRadius: '8px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          minWidth: '160px',
          zIndex: 100,
          overflow: 'hidden',
        }}>
          <button onClick={() => { setShowUserMenu(false); navigate('/profile'); }}
            style={menuItemStyle}>Profile</button>
          <button onClick={() => { setShowUserMenu(false); navigate('/history'); }}
            style={menuItemStyle}>My Sessions</button>
          <button onClick={() => { setShowUserMenu(false); navigate('/scorecard'); }}
            style={menuItemStyle}>My Scorecard</button>
          <button onClick={handleLogout}
            style={{ ...menuItemStyle, color: '#e53e3e' }}>Log Out</button>
        </div>
      )}
    </div>
  );

  // Render selection screen
  if (selectionStep !== 'chat') {
    return (
      <div className="app">
        <header className="header" style={{ position: 'relative' }}>
          <h1>{user?.name ? `Hi, ${user.name}!` : 'Learn Like Magic'}</h1>
          <p className="subtitle">
            {BOARD} • Grade {GRADE} • {COUNTRY}
          </p>
          <UserMenu />
        </header>

        <div className="selection-container">
          {selectionStep === 'subject' && (
            <div className="selection-step">
              <h2>Select a Subject</h2>
              {loading ? (
                <p>Loading subjects...</p>
              ) : (
                <div className="selection-grid" data-testid="subject-list">
                  {subjects.map((subject) => (
                    <button
                      key={subject}
                      className="selection-card"
                      data-testid="subject-item"
                      onClick={() => handleSubjectSelect(subject)}
                    >
                      {subject}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {selectionStep === 'topic' && (
            <div className="selection-step">
              <button className="back-button" onClick={handleBack}>
                ← Back
              </button>
              <h2>{selectedSubject} - Select a Topic</h2>
              {loading ? (
                <p>Loading topics...</p>
              ) : (
                <div className="selection-grid" data-testid="topic-list">
                  {topics.map((topic) => (
                    <button
                      key={topic}
                      className="selection-card"
                      data-testid="topic-item"
                      onClick={() => handleTopicSelect(topic)}
                    >
                      {topic}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {selectionStep === 'subtopic' && (
            <div className="selection-step">
              <button className="back-button" onClick={handleBack}>
                ← Back
              </button>
              <h2>
                {selectedSubject} → {selectedTopic} - Select a Subtopic
              </h2>
              {loading ? (
                <p>Loading subtopics...</p>
              ) : (
                <div className="selection-grid" data-testid="subtopic-list">
                  {subtopics.map((subtopic) => (
                    <button
                      key={subtopic.guideline_id}
                      className="selection-card"
                      data-testid="subtopic-item"
                      onClick={() => handleSubtopicSelect(subtopic)}
                    >
                      {subtopic.subtopic}
                      {subtopicProgress[subtopic.guideline_id] && (
                        <span className={`subtopic-status ${subtopicProgress[subtopic.guideline_id].status}`}>
                          {subtopicProgress[subtopic.guideline_id].status === 'mastered' ? '\u2713' : '\u25CF'}
                          {' '}
                          {(subtopicProgress[subtopic.guideline_id].score * 100).toFixed(0)}%
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {selectionStep === 'mode' && selectedSubtopic && (
            <ModeSelection
              subtopic={selectedSubtopic}
              onSelectMode={handleModeSelect}
              onResume={handleResume}
              onBack={handleBack}
            />
          )}
        </div>
      </div>
    );
  }

  // Render chat screen (existing code)
  return (
    <>
    <div className="app">
      <header className="header" style={{ position: 'relative' }}>
        <h1>Learn Like Magic</h1>
        <p className="subtitle">
          Grade {GRADE} • {selectedSubject} • {selectedTopic} • {selectedSubtopic?.subtopic}
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
                    {showHints === idx ? '▼' : '▶'} Hints
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
              {sessionMode === 'teach_me' && !isComplete && (
                <button onClick={handlePause} className="back-button" data-testid="pause-button" style={{ fontSize: '0.8rem' }}>
                  Pause Session
                </button>
              )}
              {sessionMode === 'clarify_doubts' && !isComplete && (
                <button onClick={() => setIsComplete(true)} className="back-button" style={{ fontSize: '0.8rem' }}>
                  End Session
                </button>
              )}
              {sessionMode === 'exam' && !isComplete && (
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
            <button onClick={() => window.location.reload()} className="restart-button">
              Start New Session
            </button>
            <button
              onClick={() => navigate('/scorecard')}
              className="restart-button"
              style={{ marginTop: '10px', background: 'white', color: '#667eea', border: '2px solid #667eea' }}
            >
              View Scorecard
            </button>
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

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '10px 16px',
  border: 'none',
  background: 'none',
  textAlign: 'left' as const,
  fontSize: '0.9rem',
  cursor: 'pointer',
  color: '#333',
};

export default App;
