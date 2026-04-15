import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getExamReview, ExamReviewResponse } from '../api';
import '../App.css';

export default function ExamReviewPage() {
  const navigate = useNavigate();
  const { subject, chapter, topic, sessionId } = useParams<{
    subject: string;
    chapter: string;
    topic: string;
    sessionId: string;
  }>();

  const [data, setData] = useState<ExamReviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    getExamReview(sessionId)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleBack = () => {
    if (subject && chapter && topic) {
      navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(chapter)}/${encodeURIComponent(topic)}`);
    } else {
      navigate('/learn');
    }
  };

  if (loading) {
    return (
      <div className="app-content-inner">
        <p className="page-loading">Loading exam review...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="app-content-inner">
        <div className="auth-error" role="alert" aria-live="assertive">{error || 'Failed to load exam review'}</div>
        <button onClick={handleBack} className="content-back-link">Go Back</button>
      </div>
    );
  }

  const feedback = data.exam_feedback;
  const totalScore = feedback ? feedback.score : data.questions.reduce((sum, q) => sum + q.score, 0);
  const totalQuestions = feedback ? feedback.total : data.questions.length;
  const percentage = feedback ? feedback.percentage : (totalQuestions > 0 ? (totalScore / totalQuestions) * 100 : 0);

  const getScoreColor = (pct: number) =>
    pct >= 70 ? '#38a169' : pct >= 40 ? '#dd6b20' : '#e53e3e';

  return (
    <div className="app-content-inner">
      <button className="content-back-link" onClick={handleBack}>
        &larr; Back
      </button>

      <h2 className="page-title">Exam Review</h2>
      {data.created_at && (
        <p className="exam-review-date">
          {new Date(data.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
        </p>
      )}

      <div className="exam-review-score">
        <div className="exam-review-score-value" style={{ color: getScoreColor(percentage) }}>
          {totalScore % 1 === 0 ? totalScore.toFixed(0) : totalScore.toFixed(1)}/{totalQuestions}
        </div>
        <div className="exam-review-score-pct">{percentage.toFixed(1)}%</div>
      </div>

      <div className="exam-review-questions">
        {data.questions.map((r) => {
          const scoreColor = r.score >= 0.8 ? '#38a169' : r.score >= 0.2 ? '#dd6b20' : '#e53e3e';
          return (
            <div key={r.question_idx} className="exam-review-question">
              <div className="exam-review-question-header">
                <span className="exam-review-question-num">Q{r.question_idx + 1}</span>
                <span className="exam-review-question-score" style={{ color: scoreColor }}>
                  {r.score % 1 === 0 ? r.score.toFixed(0) : r.score.toFixed(1)}/1
                </span>
              </div>
              <p className="exam-review-question-text">{r.question_text}</p>
              <div className="exam-review-answer">
                <strong>Your answer:</strong> {r.student_answer || '(no answer)'}
              </div>
              {r.expected_answer && (
                <div className="exam-review-answer">
                  <strong>Expected:</strong> {r.expected_answer}
                </div>
              )}
              {r.marks_rationale && (
                <div className="exam-review-rationale">
                  {r.marks_rationale}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {feedback && feedback.next_steps && feedback.next_steps.length > 0 && (
        <div className="exam-review-next-steps">
          <strong>Next Steps:</strong>
          <ul>
            {feedback.next_steps.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
