import React, { useEffect, useState } from 'react';
import { getGuidelineSessions, getTopicProgress, GuidelineSessionEntry, TopicInfo } from '../api';

type SelectableMode = 'teach_me' | 'clarify_doubts' | 'exam' | 'practice';

const MODE_LOADING_MESSAGES: Record<string, string> = {
  teach_me: 'Preparing your lesson...',
  clarify_doubts: 'Getting ready for your questions...',
  exam: 'Preparing your question paper...',
  practice: 'Setting up your practice session...',
};

interface ModeSelectionProps {
  topic: TopicInfo;
  onSelectMode: (mode: SelectableMode) => void;
  onResume: (sessionId: string, mode: string) => void;
  onBack: () => void;
  onViewExamReview: (sessionId: string) => void;
  creatingMode?: SelectableMode | null;
}

function formatRelativeDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '';
  const then = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - then.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return 'today';
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 14) return 'last week';
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  return `${Math.floor(diffDays / 30)} months ago`;
}

function ModeSelection({ topic, onSelectMode, onResume, onBack, onViewExamReview, creatingMode }: ModeSelectionProps) {
  const [sessions, setSessions] = useState<GuidelineSessionEntry[]>([]);
  const [lastPracticed, setLastPracticed] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPastExams, setShowPastExams] = useState(false);

  const isRefresher = topic.topic_key === 'get-ready';

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getGuidelineSessions(topic.guideline_id).catch(() => [] as GuidelineSessionEntry[]),
      getTopicProgress().catch(() => ({} as Record<string, any>)),
    ])
      .then(([sessionsData, progressData]) => {
        if (cancelled) return;
        setSessions(sessionsData);
        const progress = progressData[topic.guideline_id];
        setLastPracticed(progress?.last_practiced ?? null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [topic.guideline_id]);

  // Find incomplete sessions for resume — only show if there's actual progress
  const incompleteExam = isRefresher ? undefined : sessions.find((s) => s.mode === 'exam' && !s.is_complete && (s.exam_answered ?? 0) > 0);
  const incompleteTeachMe = sessions.find((s) => s.mode === 'teach_me' && !s.is_complete && (s.coverage ?? 0) > 0);
  const incompletePractice = isRefresher ? undefined : sessions.find(
    (s) => s.mode === 'practice' && !s.is_complete && (s.practice_questions_answered ?? 0) > 0
  );

  // Completed exams for past exams section
  const completedExams = isRefresher ? [] : sessions.filter((s) => s.mode === 'exam' && s.is_complete);

  return (
    <div className="selection-step">
      <button className="back-button" onClick={onBack}>
        ← Back
      </button>
      <h2>{topic.topic}</h2>
      <p className="mode-desc">What would you like to do?</p>

      {creatingMode ? (
        <div className="mode-loading">
          <div className="typing-indicator" style={{ justifyContent: 'center' }}>
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p className="mode-loading-title">
            {MODE_LOADING_MESSAGES[creatingMode]}
          </p>
          <p className="mode-loading-sub">
            This may take a moment
          </p>
        </div>
      ) : loading ? (
        <p>Loading...</p>
      ) : (
        <>
          {/* Resume cards */}
          {incompleteExam && (
            <button
              className="selection-card resume-card"
              onClick={() => onResume(incompleteExam.session_id, 'exam')}
              style={{
                background: 'linear-gradient(135deg, #ed8936 0%, #dd6b20 100%)',
                marginBottom: '10px',
                width: '100%',
              }}
            >
              <strong>Resume Exam</strong>
              <span className="mode-card-sub">
                {incompleteExam.exam_answered != null && incompleteExam.exam_total != null
                  ? `${incompleteExam.exam_answered}/${incompleteExam.exam_total} answered`
                  : 'In progress'} — continue your exam
              </span>
            </button>
          )}

          <div className="selection-grid" data-testid="mode-selection" style={{ gridTemplateColumns: '1fr' }}>
            {incompleteTeachMe ? (
              <>
                <button
                  className="selection-card resume-card"
                  onClick={() => onResume(incompleteTeachMe.session_id, 'teach_me')}
                  style={{
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  }}
                >
                  <strong>Continue Lesson</strong>
                  <span className="mode-card-sub">
                    {incompleteTeachMe.coverage != null ? `${incompleteTeachMe.coverage.toFixed(0)}% covered` : 'In progress'} — pick up where you left off
                  </span>
                </button>
                <button className="selection-card" data-testid="mode-teach-me" onClick={() => onSelectMode('teach_me')}>
                  <strong>Start Fresh</strong>
                  <span className="mode-card-sub">
                    Start a new lesson from scratch
                  </span>
                </button>
              </>
            ) : (
              <button className="selection-card" data-testid="mode-teach-me" onClick={() => onSelectMode('teach_me')}>
                <strong>{isRefresher ? 'Get Ready' : 'Teach Me'}</strong>
                <span className="mode-card-sub">
                  {isRefresher ? 'Review the prerequisites for this chapter' : 'Learn this topic step by step'}
                </span>
              </button>
            )}
            {!isRefresher && incompletePractice && (
              <button
                className="selection-card resume-card"
                onClick={() => onResume(incompletePractice.session_id, 'practice')}
                style={{
                  background: 'linear-gradient(135deg, #38a169 0%, #2f855a 100%)',
                }}
              >
                <strong>Resume Practice</strong>
                <span className="mode-card-sub">
                  {incompletePractice.practice_questions_answered ?? 0} question(s) answered — pick up where you left off
                </span>
              </button>
            )}
            {!isRefresher && !incompletePractice && (
              <button className="selection-card" data-testid="mode-practice" onClick={() => onSelectMode('practice')}>
                <strong>Let's Practice</strong>
                <span className="mode-card-sub">
                  Practice what you learned
                </span>
                {lastPracticed && (
                  <span className="mode-practiced-note">
                    Practiced {formatRelativeDate(lastPracticed)}
                  </span>
                )}
              </button>
            )}
            {!isRefresher && (
              <button className="selection-card" data-testid="mode-clarify-doubts" onClick={() => onSelectMode('clarify_doubts')}>
                <strong>Clarify Doubts</strong>
                <span className="mode-card-sub">
                  Ask me anything about this topic
                </span>
              </button>
            )}
            {!isRefresher && !incompleteExam && (
              <button className="selection-card" data-testid="mode-exam" onClick={() => onSelectMode('exam')}>
                <strong>Take Exam</strong>
                <span className="mode-card-sub">
                  Formal test with a score
                </span>
              </button>
            )}
          </div>

          {/* Past exams section */}
          {completedExams.length > 0 && (
            <div className="past-exams-section">
              <button
                className="past-exams-toggle"
                onClick={() => setShowPastExams(!showPastExams)}
              >
                {showPastExams ? '\u25BC' : '\u25B6'} Past Exams ({completedExams.length})
              </button>
              {showPastExams && (
                <div className="past-exams-list">
                  {completedExams.map((exam) => {
                    const score = exam.exam_score ?? 0;
                    const total = exam.exam_total ?? 0;
                    const pct = total > 0 ? (score / total) * 100 : 0;
                    const scoreTier = pct >= 70 ? 'high' : pct >= 40 ? 'mid' : 'low';
                    return (
                      <button
                        key={exam.session_id}
                        className="past-exam-row"
                        onClick={() => onViewExamReview(exam.session_id)}
                      >
                        <span className="past-exam-date">
                          {exam.created_at
                            ? new Date(exam.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                            : 'Exam'}
                        </span>
                        <span className={`past-exam-score past-exam-score--${scoreTier}`}>
                          {score % 1 === 0 ? score.toFixed(0) : score.toFixed(1)}/{total} ({pct.toFixed(0)}%)
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ModeSelection;
