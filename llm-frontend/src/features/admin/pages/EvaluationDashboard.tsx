/**
 * Evaluation Dashboard - View evaluation runs, start new evaluations, and inspect results
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  listEvalRuns,
  getEvalRun,
  startEvaluation,
  getEvalStatus,
  listSessions,
  evaluateSession,
  getAllGuidelinesForReview,
} from '../api/adminApi';
import { EvalRunSummary, EvalRunDetail, EvalStatus, SessionSummary, GuidelineReview } from '../types';

const DIMENSIONS = [
  'coherence',
  'non_repetition',
  'natural_flow',
  'engagement',
  'responsiveness',
  'pacing',
  'grade_appropriateness',
  'topic_coverage',
  'session_arc',
  'overall_naturalness',
];

function dimensionLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function scoreColor(score: number): string {
  if (score >= 7) return '#10B981';
  if (score >= 4) return '#D97706';
  return '#DC2626';
}

function severityColor(severity: string): { bg: string; text: string } {
  switch (severity) {
    case 'critical':
      return { bg: '#FEE2E2', text: '#991B1B' };
    case 'major':
      return { bg: '#FEF3C7', text: '#92400E' };
    default:
      return { bg: '#E0E7FF', text: '#3730A3' };
  }
}

// ──────────────────────────────────────
// Status Banner
// ──────────────────────────────────────

const StatusBanner: React.FC<{
  status: EvalStatus;
  onComplete: () => void;
  onDismiss: () => void;
}> = ({ status, onComplete, onDismiss }) => {
  const prevStatusRef = useRef(status.status);

  useEffect(() => {
    if (
      prevStatusRef.current !== 'complete' &&
      prevStatusRef.current !== 'idle' &&
      (status.status === 'complete' || status.status === 'failed')
    ) {
      onComplete();
    }
    prevStatusRef.current = status.status;
  }, [status.status, onComplete]);

  if (status.status === 'idle') return null;

  const isRunning = !['complete', 'failed', 'idle'].includes(status.status);
  const isDone = status.status === 'complete' || status.status === 'failed';
  const bgColor =
    status.status === 'failed'
      ? '#FEE2E2'
      : status.status === 'complete'
        ? '#D1FAE5'
        : '#EEF2FF';
  const textColor =
    status.status === 'failed'
      ? '#991B1B'
      : status.status === 'complete'
        ? '#065F46'
        : '#3730A3';

  // For failed status, show the error message; for others show the detail
  const displayText =
    status.status === 'failed' && status.error
      ? `Failed: ${status.error}`
      : status.detail || status.status;

  return (
    <div
      style={{
        padding: '12px 16px',
        backgroundColor: bgColor,
        color: textColor,
        borderRadius: '8px',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        fontSize: '14px',
      }}
    >
      {isRunning && (
        <span
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: '#4F46E5',
            animation: 'pulse 1.5s infinite',
          }}
        />
      )}
      <span style={{ fontWeight: '500', flex: 1, minWidth: 0 }}>
        {displayText}
      </span>
      {status.max_turns > 0 && isRunning && (
        <span style={{ fontSize: '13px', opacity: 0.8, flexShrink: 0 }}>
          Turn {status.turn}/{status.max_turns}
        </span>
      )}
      {status.run_id && (
        <span style={{ fontSize: '12px', opacity: 0.7, flexShrink: 0 }}>
          {status.run_id}
        </span>
      )}
      {isDone && (
        <button
          onClick={onDismiss}
          style={{
            background: 'none',
            border: 'none',
            color: textColor,
            cursor: 'pointer',
            fontSize: '18px',
            lineHeight: 1,
            padding: '0 2px',
            opacity: 0.6,
            flexShrink: 0,
          }}
        >
          ×
        </button>
      )}
    </div>
  );
};

// ──────────────────────────────────────
// Score Bar
// ──────────────────────────────────────

const ScoreBar: React.FC<{ label: string; score: number; analysis?: string }> = ({
  label,
  score,
  analysis,
}) => {
  const [expanded, setExpanded] = useState(false);
  const color = scoreColor(score);

  return (
    <div style={{ marginBottom: '8px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          cursor: analysis ? 'pointer' : 'default',
        }}
        onClick={() => analysis && setExpanded(!expanded)}
      >
        <span
          style={{
            width: '160px',
            fontSize: '13px',
            color: '#4B5563',
            flexShrink: 0,
          }}
        >
          {label}
          {analysis && (
            <span style={{ color: '#9CA3AF', marginLeft: '4px' }}>
              {expanded ? '▾' : '▸'}
            </span>
          )}
        </span>
        <div
          style={{
            flex: 1,
            height: '20px',
            backgroundColor: '#F3F4F6',
            borderRadius: '4px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${score * 10}%`,
              height: '100%',
              backgroundColor: color,
              borderRadius: '4px',
              transition: 'width 0.3s ease',
            }}
          />
        </div>
        <span
          style={{
            width: '32px',
            textAlign: 'right',
            fontWeight: '600',
            fontSize: '14px',
            color,
          }}
        >
          {score}
        </span>
      </div>
      {expanded && analysis && (
        <div
          style={{
            marginTop: '6px',
            marginLeft: '170px',
            fontSize: '13px',
            color: '#6B7280',
            lineHeight: '1.5',
            padding: '8px 12px',
            backgroundColor: '#F9FAFB',
            borderRadius: '6px',
          }}
        >
          {analysis}
        </div>
      )}
    </div>
  );
};

// ──────────────────────────────────────
// Run Detail View
// ──────────────────────────────────────

const RunDetailView: React.FC<{
  run: EvalRunDetail;
  onBack: () => void;
}> = ({ run, onBack }) => {
  const evaluation = run.evaluation;

  return (
    <div>
      {/* Back + header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '20px',
        }}
      >
        <button
          onClick={onBack}
          style={{
            padding: '6px 12px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
          }}
        >
          ← Back
        </button>
        <h2 style={{ margin: 0, fontSize: '20px', fontWeight: '600' }}>
          {run.run_id}
        </h2>
        {run.config?.topic_id && (
          <span style={{ fontSize: '13px', color: '#6B7280' }}>
            Topic: {run.config.topic_id}
          </span>
        )}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {run.config?.tutor_llm_provider && (
            <span style={{
              padding: '2px 8px',
              background: '#EEF2FF',
              color: '#4338CA',
              borderRadius: '10px',
              fontSize: '11px',
              fontWeight: 500,
            }}>
              ⚡ Tutor: {({'openai': 'GPT-5.2', 'anthropic': 'Claude Opus 4.6', 'anthropic-haiku': 'Claude Haiku 4.5'} as Record<string, string>)[run.config.tutor_llm_provider] || run.config.tutor_llm_provider}
            </span>
          )}
          {run.config?.eval_llm_provider && (
            <span style={{
              padding: '2px 8px',
              background: '#FEF3C7',
              color: '#92400E',
              borderRadius: '10px',
              fontSize: '11px',
              fontWeight: 500,
            }}>
              🔍 Evaluator: {({'openai': 'GPT-5.2', 'anthropic': 'Claude Opus 4.6'} as Record<string, string>)[run.config.eval_llm_provider] || run.config.eval_llm_provider}
            </span>
          )}
        </div>
      </div>

      {/* Score summary */}
      {evaluation && (
        <div
          style={{
            backgroundColor: 'white',
            border: '1px solid #E5E7EB',
            borderRadius: '8px',
            padding: '20px',
            marginBottom: '20px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
              marginBottom: '16px',
            }}
          >
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600' }}>
              Scores
            </h3>
            <span
              style={{
                padding: '4px 12px',
                borderRadius: '12px',
                backgroundColor: scoreColor(evaluation.avg_score) + '20',
                color: scoreColor(evaluation.avg_score),
                fontWeight: '600',
                fontSize: '14px',
              }}
            >
              Avg: {evaluation.avg_score.toFixed(1)}
            </span>
          </div>
          {DIMENSIONS.map((dim) => (
            <ScoreBar
              key={dim}
              label={dimensionLabel(dim)}
              score={evaluation.scores[dim] ?? 0}
              analysis={evaluation.dimension_analysis?.[dim]}
            />
          ))}
        </div>
      )}

      {/* Summary */}
      {evaluation?.summary && (
        <div
          style={{
            backgroundColor: 'white',
            border: '1px solid #E5E7EB',
            borderRadius: '8px',
            padding: '20px',
            marginBottom: '20px',
          }}
        >
          <h3 style={{ margin: '0 0 10px', fontSize: '16px', fontWeight: '600' }}>
            Overall Assessment
          </h3>
          <p
            style={{
              margin: 0,
              fontSize: '14px',
              color: '#4B5563',
              lineHeight: '1.6',
              whiteSpace: 'pre-wrap',
            }}
          >
            {evaluation.summary}
          </p>
        </div>
      )}

      {/* Problems */}
      {evaluation?.problems && evaluation.problems.length > 0 && (
        <div
          style={{
            backgroundColor: 'white',
            border: '1px solid #E5E7EB',
            borderRadius: '8px',
            padding: '20px',
            marginBottom: '20px',
          }}
        >
          <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: '600' }}>
            Problems ({evaluation.problems.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {evaluation.problems.map((problem, i) => {
              const sev = severityColor(problem.severity);
              return (
                <div
                  key={i}
                  style={{
                    padding: '14px',
                    backgroundColor: '#F9FAFB',
                    borderRadius: '8px',
                    border: '1px solid #E5E7EB',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      marginBottom: '8px',
                    }}
                  >
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        backgroundColor: sev.bg,
                        color: sev.text,
                        fontSize: '11px',
                        fontWeight: '600',
                        textTransform: 'uppercase',
                      }}
                    >
                      {problem.severity}
                    </span>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        backgroundColor: '#F3F4F6',
                        color: '#6B7280',
                        fontSize: '11px',
                      }}
                    >
                      {problem.root_cause.replace(/_/g, ' ')}
                    </span>
                    <span style={{ fontSize: '12px', color: '#9CA3AF' }}>
                      Turns: {problem.turns.join(', ')}
                    </span>
                  </div>
                  <h4
                    style={{
                      margin: '0 0 6px',
                      fontSize: '14px',
                      fontWeight: '600',
                      color: '#111827',
                    }}
                  >
                    {problem.title}
                  </h4>
                  <p
                    style={{
                      margin: '0 0 8px',
                      fontSize: '13px',
                      color: '#4B5563',
                      lineHeight: '1.5',
                    }}
                  >
                    {problem.description}
                  </p>
                  {problem.quote && (
                    <div
                      style={{
                        padding: '8px 12px',
                        borderLeft: '3px solid #D1D5DB',
                        backgroundColor: 'white',
                        fontSize: '13px',
                        color: '#6B7280',
                        fontStyle: 'italic',
                      }}
                    >
                      "{problem.quote}"
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Conversation transcript */}
      {run.messages && run.messages.length > 0 && (
        <div
          style={{
            backgroundColor: 'white',
            border: '1px solid #E5E7EB',
            borderRadius: '8px',
            padding: '20px',
          }}
        >
          <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: '600' }}>
            Conversation ({run.messages.length} messages)
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {run.messages.map((msg, i) => {
              const isTutor = msg.role === 'tutor';
              return (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    justifyContent: isTutor ? 'flex-start' : 'flex-end',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '75%',
                      padding: '10px 14px',
                      borderRadius: isTutor
                        ? '4px 12px 12px 12px'
                        : '12px 4px 12px 12px',
                      backgroundColor: isTutor ? '#EEF2FF' : '#F0FDF4',
                      border: `1px solid ${isTutor ? '#C7D2FE' : '#BBF7D0'}`,
                    }}
                  >
                    <div
                      style={{
                        fontSize: '11px',
                        color: '#9CA3AF',
                        marginBottom: '4px',
                        display: 'flex',
                        gap: '8px',
                      }}
                    >
                      <span style={{ fontWeight: '600', color: isTutor ? '#4F46E5' : '#059669' }}>
                        {isTutor ? 'Tutor' : 'Student'}
                      </span>
                      <span>Turn {msg.turn}</span>
                    </div>
                    <div
                      className="eval-message-content"
                      style={{
                        fontSize: '14px',
                        color: '#1F2937',
                        lineHeight: '1.6',
                      }}
                    >
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No evaluation yet */}
      {!evaluation && (
        <div
          style={{
            textAlign: 'center',
            padding: '40px 20px',
            backgroundColor: '#F9FAFB',
            borderRadius: '8px',
            border: '2px dashed #D1D5DB',
          }}
        >
          <p style={{ fontSize: '16px', color: '#6B7280' }}>
            No evaluation results yet
          </p>
          <p style={{ fontSize: '14px', color: '#9CA3AF' }}>
            This run may still be in progress or evaluation was not completed.
          </p>
        </div>
      )}
    </div>
  );
};

// ──────────────────────────────────────
// Evaluation Form Panel (two modes)
// ──────────────────────────────────────

type EvalMode = 'existing' | 'simulated';

const EvalFormPanel: React.FC<{
  onStartSimulated: (topicId: string, maxTurns: number) => void;
  onStartSession: (sessionId: string) => void;
  onCancel: () => void;
  starting: boolean;
}> = ({ onStartSimulated, onStartSession, onCancel, starting }) => {
  const [mode, setMode] = useState<EvalMode>('existing');
  const [topicId, setTopicId] = useState('');
  const [maxTurns, setMaxTurns] = useState(20);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [guidelines, setGuidelines] = useState<GuidelineReview[]>([]);
  const [loadingGuidelines, setLoadingGuidelines] = useState(false);

  useEffect(() => {
    if (mode === 'existing' && sessions.length === 0) {
      setLoadingSessions(true);
      listSessions()
        .then((res) => setSessions(res.sessions))
        .catch(() => {})
        .finally(() => setLoadingSessions(false));
    }
    if (mode === 'simulated' && guidelines.length === 0) {
      setLoadingGuidelines(true);
      getAllGuidelinesForReview({ status: 'APPROVED' })
        .then((data) => setGuidelines(data))
        .catch(() => {})
        .finally(() => setLoadingGuidelines(false));
    }
  }, [mode, sessions.length, guidelines.length]);

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '8px 16px',
    fontSize: '13px',
    fontWeight: active ? '600' : '400',
    color: active ? '#4F46E5' : '#6B7280',
    backgroundColor: active ? 'white' : 'transparent',
    border: active ? '1px solid #E5E7EB' : '1px solid transparent',
    borderBottom: active ? '1px solid white' : '1px solid #E5E7EB',
    borderRadius: '6px 6px 0 0',
    cursor: 'pointer',
    marginBottom: '-1px',
  });

  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);

  return (
    <div
      style={{
        backgroundColor: '#F9FAFB',
        borderRadius: '8px',
        border: '1px solid #E5E7EB',
        marginBottom: '16px',
        overflow: 'hidden',
      }}
    >
      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '0',
          borderBottom: '1px solid #E5E7EB',
          padding: '0 16px',
          backgroundColor: '#F3F4F6',
        }}
      >
        <button style={tabStyle(mode === 'existing')} onClick={() => setMode('existing')}>
          Evaluate Existing Session
        </button>
        <button style={tabStyle(mode === 'simulated')} onClick={() => setMode('simulated')}>
          New Simulated Session
        </button>
      </div>

      <div style={{ padding: '16px' }}>
        {mode === 'existing' ? (
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '250px' }}>
              <label
                style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}
              >
                Select Session
              </label>
              {loadingSessions ? (
                <div style={{ padding: '8px 0', fontSize: '13px', color: '#9CA3AF' }}>
                  Loading sessions...
                </div>
              ) : sessions.length === 0 ? (
                <div style={{ padding: '8px 0', fontSize: '13px', color: '#9CA3AF' }}>
                  No sessions found. Start a tutoring session first.
                </div>
              ) : (
                <select
                  value={selectedSessionId}
                  onChange={(e) => setSelectedSessionId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    fontSize: '14px',
                    boxSizing: 'border-box',
                    backgroundColor: 'white',
                  }}
                >
                  <option value="">Choose a session...</option>
                  {sessions.map((s) => (
                    <option key={s.session_id} value={s.session_id}>
                      {s.topic_name || 'Untitled'} - {s.message_count} msgs
                      {s.created_at ? ` - ${new Date(s.created_at).toLocaleDateString()}` : ''}
                    </option>
                  ))}
                </select>
              )}
              {selectedSession && selectedSession.message_count === 0 && (
                <div style={{ fontSize: '12px', color: '#D97706', marginTop: '4px' }}>
                  This session has no messages. Evaluation may not produce meaningful results.
                </div>
              )}
            </div>
            <button
              onClick={() => onStartSession(selectedSessionId)}
              disabled={!selectedSessionId || starting}
              style={{
                padding: '8px 20px',
                backgroundColor: !selectedSessionId || starting ? '#9CA3AF' : '#4F46E5',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: !selectedSessionId || starting ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: '500',
              }}
            >
              {starting ? 'Starting...' : 'Evaluate'}
            </button>
            <button
              onClick={onCancel}
              style={{
                padding: '8px 16px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Cancel
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '250px' }}>
              <label
                style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}
              >
                Select Guideline
              </label>
              {loadingGuidelines ? (
                <div style={{ padding: '8px 0', fontSize: '13px', color: '#9CA3AF' }}>
                  Loading guidelines...
                </div>
              ) : guidelines.length === 0 ? (
                <div style={{ padding: '8px 0', fontSize: '13px', color: '#9CA3AF' }}>
                  No approved guidelines found.
                </div>
              ) : (
                <select
                  value={topicId}
                  onChange={(e) => setTopicId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: '1px solid #D1D5DB',
                    fontSize: '14px',
                    boxSizing: 'border-box',
                    backgroundColor: 'white',
                  }}
                >
                  <option value="">Choose a guideline...</option>
                  {guidelines.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.subject} - {g.topic} / {g.subtopic} (Grade {g.grade})
                    </option>
                  ))}
                </select>
              )}
            </div>
            <div style={{ width: '140px' }}>
              <label
                style={{ fontSize: '12px', color: '#6B7280', display: 'block', marginBottom: '4px' }}
              >
                Max Turns: {maxTurns}
              </label>
              <input
                type="range"
                min={5}
                max={40}
                value={maxTurns}
                onChange={(e) => setMaxTurns(parseInt(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>
            <button
              onClick={() => onStartSimulated(topicId, maxTurns)}
              disabled={!topicId.trim() || starting}
              style={{
                padding: '8px 20px',
                backgroundColor: !topicId.trim() || starting ? '#9CA3AF' : '#4F46E5',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: !topicId.trim() || starting ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: '500',
              }}
            >
              {starting ? 'Starting...' : 'Start'}
            </button>
            <button
              onClick={onCancel}
              style={{
                padding: '8px 16px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

// ──────────────────────────────────────
// Run Card
// ──────────────────────────────────────

const RunCard: React.FC<{
  run: EvalRunSummary;
  onClick: () => void;
}> = ({ run, onClick }) => {
  const hasScores = run.avg_score !== null;
  const avgColor = hasScores ? scoreColor(run.avg_score!) : '#9CA3AF';

  return (
    <div
      onClick={onClick}
      style={{
        backgroundColor: 'white',
        border: '1px solid #E5E7EB',
        borderRadius: '8px',
        padding: '16px',
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow =
          '0 1px 3px rgba(0,0,0,0.1)';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow = 'none';
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '10px',
        }}
      >
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '4px',
            }}
          >
            <span
              style={{
                fontSize: '15px',
                fontWeight: '600',
                color: '#111827',
              }}
            >
              {run.run_id}
            </span>
            <span
              style={{
                padding: '1px 8px',
                borderRadius: '10px',
                fontSize: '11px',
                fontWeight: '500',
                backgroundColor: run.source === 'existing_session' ? '#DBEAFE' : '#F3E8FF',
                color: run.source === 'existing_session' ? '#1D4ED8' : '#7C3AED',
              }}
            >
              {run.source === 'existing_session' ? 'Session' : 'Simulated'}
            </span>
          </div>
          <div style={{ fontSize: '12px', color: '#6B7280' }}>
            {new Date(run.timestamp).toLocaleString()} · {run.message_count}{' '}
            messages
          </div>
        </div>
        {hasScores ? (
          <div
            style={{
              padding: '6px 14px',
              borderRadius: '16px',
              backgroundColor: avgColor + '15',
              color: avgColor,
              fontWeight: '700',
              fontSize: '16px',
            }}
          >
            {run.avg_score!.toFixed(1)}
          </div>
        ) : (
          <span
            style={{
              padding: '4px 10px',
              backgroundColor: '#F3F4F6',
              borderRadius: '12px',
              fontSize: '12px',
              color: '#9CA3AF',
            }}
          >
            No scores
          </span>
        )}
      </div>

      {/* Topic ID */}
      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '10px' }}>
        Topic: {run.topic_id || 'N/A'}
      </div>

      {/* Mini score bars */}
      {hasScores && Object.keys(run.scores).length > 0 && (
        <div style={{ display: 'flex', gap: '3px', height: '6px' }}>
          {DIMENSIONS.map((dim) => {
            const score = run.scores[dim];
            if (score === undefined) return null;
            return (
              <div
                key={dim}
                title={`${dimensionLabel(dim)}: ${score}`}
                style={{
                  flex: 1,
                  backgroundColor: scoreColor(score),
                  borderRadius: '2px',
                  opacity: 0.7,
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};

// ──────────────────────────────────────
// Main Dashboard
// ──────────────────────────────────────

const EvaluationDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail view
  const [selectedRun, setSelectedRun] = useState<EvalRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Start form
  const [showStartForm, setShowStartForm] = useState(false);
  const [starting, setStarting] = useState(false);

  // Live status polling
  const [evalStatus, setEvalStatus] = useState<EvalStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listEvalRuns();
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load runs');
    } finally {
      setLoading(false);
    }
  }, []);

  const pollStatus = useCallback(async () => {
    try {
      const status = await getEvalStatus();
      setEvalStatus(status);

      if (['idle', 'complete', 'failed'].includes(status.status)) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    } catch {
      // Ignore polling errors
    }
  }, []);

  useEffect(() => {
    loadRuns();
    // Initial status check
    pollStatus();
  }, [loadRuns, pollStatus]);

  // Start polling when an eval is running
  useEffect(() => {
    if (
      evalStatus &&
      !['idle', 'complete', 'failed'].includes(evalStatus.status) &&
      !pollRef.current
    ) {
      pollRef.current = setInterval(pollStatus, 2000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [evalStatus, pollStatus]);

  const handleSelectRun = async (runId: string) => {
    try {
      setDetailLoading(true);
      const detail = await getEvalRun(runId);
      setSelectedRun(detail);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to load run');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleStartEval = async (topicId: string, maxTurns: number) => {
    try {
      setStarting(true);
      await startEvaluation({ topic_id: topicId, max_turns: maxTurns });
      setShowStartForm(false);
      // Start polling
      const status = await getEvalStatus();
      setEvalStatus(status);
      if (!pollRef.current) {
        pollRef.current = setInterval(pollStatus, 2000);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to start evaluation');
    } finally {
      setStarting(false);
    }
  };

  const handleStartSessionEval = async (sessionId: string) => {
    try {
      setStarting(true);
      await evaluateSession({ session_id: sessionId });
      setShowStartForm(false);
      const status = await getEvalStatus();
      setEvalStatus(status);
      if (!pollRef.current) {
        pollRef.current = setInterval(pollStatus, 2000);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to start session evaluation');
    } finally {
      setStarting(false);
    }
  };

  const handleStatusComplete = useCallback(() => {
    loadRuns();
  }, [loadRuns]);

  const handleDismissStatus = useCallback(() => {
    setEvalStatus(null);
  }, []);

  // Detail view
  if (selectedRun) {
    return (
      <div style={{ padding: '20px', maxWidth: '1000px', margin: '0 auto' }}>
        {evalStatus && (
          <StatusBanner status={evalStatus} onComplete={handleStatusComplete} onDismiss={handleDismissStatus} />
        )}
        <RunDetailView
          run={selectedRun}
          onBack={() => setSelectedRun(null)}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: '20px', maxWidth: '1000px', margin: '0 auto' }}>
      {/* Animations + markdown message styles */}
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .eval-message-content p { margin: 0 0 8px; }
        .eval-message-content p:last-child { margin-bottom: 0; }
        .eval-message-content ul, .eval-message-content ol { margin: 4px 0 8px; padding-left: 20px; }
        .eval-message-content li { margin-bottom: 2px; }
        .eval-message-content strong { font-weight: 600; }
        .eval-message-content em { font-style: italic; }
        .eval-message-content code { background: rgba(0,0,0,0.06); padding: 1px 4px; border-radius: 3px; font-size: 13px; }
        .eval-message-content blockquote { margin: 6px 0; padding: 4px 10px; border-left: 3px solid #D1D5DB; color: #6B7280; }
        .eval-message-content h1, .eval-message-content h2, .eval-message-content h3 { margin: 8px 0 4px; font-size: 14px; font-weight: 600; }
      `}</style>

      {/* Status banner */}
      {evalStatus && (
        <StatusBanner status={evalStatus} onComplete={handleStatusComplete} onDismiss={handleDismissStatus} />
      )}

      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: '10px',
          }}
        >
          <button
            onClick={() => navigate('/admin/books')}
            style={{
              padding: '6px 12px',
              backgroundColor: 'white',
              color: '#374151',
              border: '1px solid #D1D5DB',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            ← Books
          </button>
          <h1 style={{ fontSize: '28px', fontWeight: '600', margin: 0 }}>
            Evaluation Runs
          </h1>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setShowStartForm(!showStartForm)}
              style={{
                padding: '8px 16px',
                backgroundColor: '#4F46E5',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: '500',
              }}
            >
              Start Evaluation
            </button>
            <button
              onClick={loadRuns}
              style={{
                padding: '8px 16px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Refresh
            </button>
          </div>
        </div>
        <p style={{ color: '#6B7280', margin: 0 }}>
          Run automated tutoring sessions and evaluate tutor performance across
          10 dimensions
        </p>
      </div>

      {/* Start form */}
      {showStartForm && (
        <EvalFormPanel
          onStartSimulated={handleStartEval}
          onStartSession={handleStartSessionEval}
          onCancel={() => setShowStartForm(false)}
          starting={starting}
        />
      )}

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          <p>Loading evaluation runs...</p>
        </div>
      )}

      {/* Detail loading overlay */}
      {detailLoading && (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          <p>Loading run details...</p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            padding: '15px',
            backgroundColor: '#FEE2E2',
            color: '#991B1B',
            borderRadius: '6px',
            marginBottom: '20px',
          }}
        >
          {error}
        </div>
      )}

      {/* Runs list */}
      {!loading && !error && (
        <div>
          {runs.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '60px 20px',
                backgroundColor: '#F9FAFB',
                borderRadius: '8px',
                border: '2px dashed #D1D5DB',
              }}
            >
              <p
                style={{
                  fontSize: '18px',
                  color: '#6B7280',
                  marginBottom: '10px',
                }}
              >
                No evaluation runs yet
              </p>
              <p style={{ color: '#9CA3AF' }}>
                Click "Start Evaluation" to run your first automated tutoring
                evaluation
              </p>
            </div>
          ) : (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}
            >
              {runs.map((run) => (
                <RunCard
                  key={run.run_id}
                  run={run}
                  onClick={() => handleSelectRun(run.run_id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default EvaluationDashboard;
