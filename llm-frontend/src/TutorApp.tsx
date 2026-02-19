import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  createSession,
  submitStep,
  getSummary,
  getCurriculum,
  getModelConfig,
  Turn,
  SummaryResponse,
  SubtopicInfo,
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
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Selection state
  const [selectionStep, setSelectionStep] = useState<
    'subject' | 'topic' | 'subtopic' | 'chat'
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
      .then((config) => setModelLabel(config.tutor.model_label))
      .catch(() => setModelLabel(''));
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
    } catch (error) {
      console.error('Failed to fetch subtopics:', error);
      alert('Failed to load subtopics.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubtopicSelect = async (subtopic: SubtopicInfo) => {
    setSelectedSubtopic(subtopic);
    await startSession(subtopic);
  };

  const startSession = async (subtopic: SubtopicInfo) => {
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

  const handleBack = () => {
    if (selectionStep === 'topic') {
      setSelectionStep('subject');
      setSelectedSubject(null);
    } else if (selectionStep === 'subtopic') {
      setSelectionStep('topic');
      setSelectedTopic(null);
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
                <div className="selection-grid">
                  {subjects.map((subject) => (
                    <button
                      key={subject}
                      className="selection-card"
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
                <div className="selection-grid">
                  {topics.map((topic) => (
                    <button
                      key={topic}
                      className="selection-card"
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
                <div className="selection-grid">
                  {subtopics.map((subtopic) => (
                    <button
                      key={subtopic.guideline_id}
                      className="selection-card"
                      onClick={() => handleSubtopicSelect(subtopic)}
                    >
                      {subtopic.subtopic}
                    </button>
                  ))}
                </div>
              )}
            </div>
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
          <span>Step {stepIdx}/10</span>
          <span>Mastery: {(mastery * 100).toFixed(0)}%</span>
        </div>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${(stepIdx / 10) * 100}%` }}
          />
        </div>
        <div className="mastery-track">
          <div
            className="mastery-fill"
            style={{ width: `${mastery * 100}%` }}
          />
        </div>
      </div>

      <div className="chat-container">
        <div className="messages">
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
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
          <form className="input-form" onSubmit={handleSubmit}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your answer..."
              disabled={loading}
              className="input-field"
            />
            <button type="submit" disabled={loading || !input.trim()} className="send-button">
              Send
            </button>
          </form>
        ) : (
          <div className="summary-card">
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
