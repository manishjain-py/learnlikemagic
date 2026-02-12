import React from 'react';
import { SessionStateResponse } from '../types';

interface Props {
  sessionState: SessionStateResponse;
}

const styles = {
  container: {
    padding: '16px',
  } as React.CSSProperties,
  header: {
    marginBottom: '16px',
  } as React.CSSProperties,
  topicName: {
    fontSize: '1.1rem',
    fontWeight: 600,
    color: '#333',
    margin: '0 0 4px 0',
  } as React.CSSProperties,
  progressLine: {
    fontSize: '0.85rem',
    color: '#666',
    margin: '0 0 8px 0',
  } as React.CSSProperties,
  progressTrack: {
    height: '6px',
    background: '#e0e0e0',
    borderRadius: '3px',
    overflow: 'hidden' as const,
  },
  progressFill: (pct: number) =>
    ({
      height: '100%',
      width: `${pct}%`,
      background: 'linear-gradient(90deg, #667eea, #764ba2)',
      transition: 'width 0.3s ease',
    }) as React.CSSProperties,
  masterySection: {
    margin: '16px 0',
  } as React.CSSProperties,
  masteryTitle: {
    fontSize: '0.8rem',
    fontWeight: 600,
    color: '#555',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: '8px',
  },
  masteryRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '6px',
    fontSize: '0.85rem',
  } as React.CSSProperties,
  masteryLabel: {
    width: '120px',
    flexShrink: 0,
    color: '#444',
    overflow: 'hidden' as const,
    textOverflow: 'ellipsis' as const,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  masteryBarTrack: {
    flex: 1,
    height: '8px',
    background: '#e8e8e8',
    borderRadius: '4px',
    overflow: 'hidden' as const,
  },
  masteryBarFill: (pct: number) =>
    ({
      height: '100%',
      width: `${pct}%`,
      background:
        pct >= 70
          ? '#4caf50'
          : pct >= 40
            ? '#ff9800'
            : '#f44336',
      transition: 'width 0.3s ease',
    }) as React.CSSProperties,
  masteryValue: {
    width: '36px',
    textAlign: 'right' as const,
    fontSize: '0.8rem',
    color: '#666',
  } as React.CSSProperties,
  stepList: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
  } as React.CSSProperties,
  stepItem: (state: 'completed' | 'current' | 'future') =>
    ({
      display: 'flex',
      alignItems: 'flex-start',
      gap: '10px',
      padding: '10px 12px',
      marginBottom: '4px',
      borderLeft: `3px solid ${
        state === 'completed'
          ? '#4caf50'
          : state === 'current'
            ? '#764ba2'
            : '#ddd'
      }`,
      background:
        state === 'current'
          ? '#f3f0ff'
          : state === 'completed'
            ? '#f9fff9'
            : 'transparent',
      opacity: state === 'future' ? 0.6 : 1,
      borderRadius: '0 6px 6px 0',
    }) as React.CSSProperties,
  stepIcon: (state: 'completed' | 'current' | 'future') =>
    ({
      width: '20px',
      height: '20px',
      borderRadius: '50%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '0.7rem',
      flexShrink: 0,
      marginTop: '1px',
      background:
        state === 'completed'
          ? '#4caf50'
          : state === 'current'
            ? '#764ba2'
            : '#ccc',
      color: 'white',
      fontWeight: 700,
    }) as React.CSSProperties,
  stepContent: {
    flex: 1,
    minWidth: 0,
  } as React.CSSProperties,
  stepTopRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '2px',
  } as React.CSSProperties,
  typeBadge: (type: string) =>
    ({
      display: 'inline-block',
      padding: '1px 6px',
      borderRadius: '3px',
      fontSize: '0.7rem',
      fontWeight: 600,
      textTransform: 'uppercase' as const,
      background:
        type === 'explain'
          ? '#e3f2fd'
          : type === 'check'
            ? '#fff3e0'
            : '#e8f5e9',
      color:
        type === 'explain'
          ? '#1565c0'
          : type === 'check'
            ? '#e65100'
            : '#2e7d32',
    }) as React.CSSProperties,
  stepConcept: {
    fontSize: '0.85rem',
    fontWeight: 500,
    color: '#333',
  } as React.CSSProperties,
  stepDetail: {
    fontSize: '0.78rem',
    color: '#888',
    marginTop: '2px',
  } as React.CSSProperties,
};

export default function StudyPlanPanel({ sessionState }: Props) {
  const topic = sessionState.topic;
  if (!topic) {
    return <div style={styles.container}>No study plan available.</div>;
  }

  const { study_plan, topic_name } = topic;
  const currentStep = sessionState.current_step;
  const totalSteps = study_plan.steps.length;
  const progressPct = totalSteps > 0 ? ((currentStep - 1) / totalSteps) * 100 : 0;

  const mastery = sessionState.mastery_estimates;
  const masteryEntries = Object.entries(mastery);

  const getStepState = (stepId: number): 'completed' | 'current' | 'future' => {
    if (stepId < currentStep) return 'completed';
    if (stepId === currentStep) return 'current';
    return 'future';
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <p style={styles.topicName}>{topic_name}</p>
        <p style={styles.progressLine}>
          Step {currentStep} of {totalSteps} &middot;{' '}
          {Math.min(100, Math.round(progressPct))}% complete
        </p>
        <div style={styles.progressTrack}>
          <div style={styles.progressFill(Math.min(100, progressPct))} />
        </div>
      </div>

      {masteryEntries.length > 0 && (
        <div style={styles.masterySection}>
          <div style={styles.masteryTitle}>Concept Mastery</div>
          {masteryEntries.map(([concept, score]) => (
            <div key={concept} style={styles.masteryRow}>
              <span style={styles.masteryLabel} title={concept}>
                {concept}
              </span>
              <div style={styles.masteryBarTrack}>
                <div style={styles.masteryBarFill(score * 100)} />
              </div>
              <span style={styles.masteryValue}>
                {Math.round(score * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}

      <ul style={styles.stepList}>
        {study_plan.steps.map((step) => {
          const state = getStepState(step.step_id);
          const detail =
            step.type === 'explain'
              ? step.content_hint
              : step.type === 'check'
                ? step.question_type
                : step.question_count
                  ? `${step.question_count} questions`
                  : null;

          return (
            <li key={step.step_id} style={styles.stepItem(state)}>
              <div style={styles.stepIcon(state)}>
                {state === 'completed' ? '\u2713' : step.step_id}
              </div>
              <div style={styles.stepContent}>
                <div style={styles.stepTopRow}>
                  <span style={styles.typeBadge(step.type)}>{step.type}</span>
                  <span style={styles.stepConcept}>{step.concept}</span>
                </div>
                {detail && <div style={styles.stepDetail}>{detail}</div>}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
