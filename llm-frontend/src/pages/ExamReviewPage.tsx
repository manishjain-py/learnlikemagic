import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getExamReview, ExamReviewResponse } from '../api';
import { useStudentProfile } from '../hooks/useStudentProfile';
import '../App.css';

export default function ExamReviewPage() {
  const navigate = useNavigate();
  const { subject, topic, subtopic, sessionId } = useParams<{
    subject: string;
    topic: string;
    subtopic: string;
    sessionId: string;
  }>();
  const { grade } = useStudentProfile();

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
    if (subject && topic && subtopic) {
      navigate(`/learn/${encodeURIComponent(subject)}/${encodeURIComponent(topic)}/${encodeURIComponent(subtopic)}`);
    } else {
      navigate('/learn');
    }
  };

  if (loading) {
    return (
      <div className="app">
        <header className="header">
          <h1>Learn Like Magic</h1>
          <p className="subtitle">Loading exam review...</p>
        </header>
        <div className="chat-container" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="app">
        <header className="header">
          <h1>Learn Like Magic</h1>
        </header>
        <div className="chat-container" style={{ padding: '2rem', textAlign: 'center' }}>
          <p style={{ color: '#e53e3e', marginBottom: '16px' }}>{error || 'Failed to load exam review'}</p>
          <button onClick={handleBack} className="back-button">Go Back</button>
        </div>
      </div>
    );
  }

  const feedback = data.exam_feedback;
  const totalScore = feedback ? feedback.score : data.questions.reduce((sum, q) => sum + q.score, 0);
  const totalQuestions = feedback ? feedback.total : data.questions.length;
  const percentage = feedback ? feedback.percentage : (totalQuestions > 0 ? (totalScore / totalQuestions) * 100 : 0);

  return (
    <div className="app">
      <header className="header">
        <h1>Learn Like Magic</h1>
        <p className="subtitle">
          Grade {grade}{subject && ` \u2022 ${subject}`}{topic && ` \u2022 ${topic}`}{subtopic && ` \u2022 ${subtopic}`}
        </p>
      </header>

      <div className="chat-container">
        <div className="summary-card" style={{ flex: 1, overflowY: 'auto' }}>
          <button className="back-button" onClick={handleBack} style={{ marginBottom: '12px' }}>
            ← Back
          </button>

          <h2>Exam Review</h2>
          {data.created_at && (
            <p style={{ fontSize: '0.8rem', color: '#718096', marginBottom: '12px' }}>
              {new Date(data.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
            </p>
          )}

          <div style={{ textAlign: 'center', margin: '12px 0 16px' }}>
            <div style={{
              fontSize: '2rem',
              fontWeight: 700,
              color: percentage >= 70 ? '#38a169' : percentage >= 40 ? '#dd6b20' : '#e53e3e',
            }}>
              {totalScore % 1 === 0 ? totalScore.toFixed(0) : totalScore.toFixed(1)}/{totalQuestions}
            </div>
            <div style={{ fontSize: '0.9rem', color: '#718096' }}>{percentage.toFixed(1)}%</div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
            {data.questions.map((r) => {
              const scoreColor = r.score >= 0.8 ? '#38a169' : r.score >= 0.2 ? '#dd6b20' : '#e53e3e';
              return (
                <div key={r.question_idx} style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '12px', background: '#fafafa' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Q{r.question_idx + 1}</span>
                    <span style={{ fontWeight: 700, color: scoreColor, fontSize: '0.9rem' }}>
                      {r.score % 1 === 0 ? r.score.toFixed(0) : r.score.toFixed(1)}/1
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

          {feedback && feedback.next_steps && feedback.next_steps.length > 0 && (
            <div style={{ marginBottom: '12px' }}>
              <strong>Next Steps:</strong>
              <ul>
                {feedback.next_steps.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
