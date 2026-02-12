import React from 'react';
import { SessionStateResponse } from '../types';

interface Props {
  sessionState: SessionStateResponse;
}

const styles = {
  container: {
    padding: '16px',
  } as React.CSSProperties,
  section: {
    marginBottom: '20px',
  } as React.CSSProperties,
  sectionTitle: {
    fontSize: '0.8rem',
    fontWeight: 600,
    color: '#555',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: '8px',
  } as React.CSSProperties,
  depthBadge: {
    display: 'inline-block',
    padding: '3px 10px',
    borderRadius: '12px',
    fontSize: '0.8rem',
    fontWeight: 500,
    background: '#e8eaf6',
    color: '#3f51b5',
  } as React.CSSProperties,
  objectiveList: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
  } as React.CSSProperties,
  objectiveItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '8px',
    padding: '6px 0',
    fontSize: '0.85rem',
    color: '#333',
    lineHeight: 1.4,
  } as React.CSSProperties,
  objectiveNumber: {
    width: '20px',
    height: '20px',
    borderRadius: '50%',
    background: '#667eea',
    color: 'white',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '0.7rem',
    fontWeight: 600,
    flexShrink: 0,
    marginTop: '1px',
  } as React.CSSProperties,
  textBlock: {
    fontSize: '0.85rem',
    color: '#444',
    lineHeight: 1.6,
    background: '#f9f9f9',
    padding: '10px 12px',
    borderRadius: '6px',
  } as React.CSSProperties,
  bulletList: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
  } as React.CSSProperties,
  bulletItem: {
    padding: '4px 0',
    fontSize: '0.85rem',
    color: '#444',
    paddingLeft: '14px',
    position: 'relative' as const,
  } as React.CSSProperties,
  bulletDot: {
    position: 'absolute' as const,
    left: 0,
    color: '#999',
  } as React.CSSProperties,
  misconceptionCard: {
    padding: '10px 12px',
    background: '#fff8e1',
    border: '1px solid #ffe082',
    borderRadius: '6px',
    marginBottom: '8px',
    fontSize: '0.85rem',
    color: '#5d4037',
    lineHeight: 1.4,
  } as React.CSSProperties,
  detectedMisconception: (resolved: boolean) =>
    ({
      padding: '10px 12px',
      background: resolved ? '#e8f5e9' : '#fce4ec',
      border: `1px solid ${resolved ? '#a5d6a7' : '#ef9a9a'}`,
      borderRadius: '6px',
      marginBottom: '8px',
      fontSize: '0.85rem',
      lineHeight: 1.4,
    }) as React.CSSProperties,
  detectedLabel: (resolved: boolean) =>
    ({
      fontSize: '0.7rem',
      fontWeight: 600,
      textTransform: 'uppercase' as const,
      color: resolved ? '#2e7d32' : '#c62828',
      marginBottom: '2px',
    }) as React.CSSProperties,
  detectedConcept: {
    fontWeight: 500,
    color: '#333',
  } as React.CSSProperties,
  detectedDesc: {
    color: '#555',
    marginTop: '2px',
  } as React.CSSProperties,
  empty: {
    fontSize: '0.85rem',
    color: '#999',
    fontStyle: 'italic' as const,
  } as React.CSSProperties,
};

export default function GuidelinesPanel({ sessionState }: Props) {
  const topic = sessionState.topic;
  if (!topic) {
    return <div style={styles.container}>No guidelines available.</div>;
  }

  const g = topic.guidelines;
  const misconceptions = sessionState.misconceptions;

  return (
    <div style={styles.container}>
      {/* Learning Objectives */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>Learning Objectives</div>
        {g.learning_objectives.length > 0 ? (
          <ol style={styles.objectiveList}>
            {g.learning_objectives.map((obj, i) => (
              <li key={i} style={styles.objectiveItem}>
                <span style={styles.objectiveNumber}>{i + 1}</span>
                <span>{obj}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p style={styles.empty}>None specified</p>
        )}
      </div>

      {/* Teaching Approach */}
      {g.teaching_approach && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Teaching Approach</div>
          <div style={styles.textBlock}>{g.teaching_approach}</div>
        </div>
      )}

      {/* Required Depth */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>Required Depth</div>
        <span style={styles.depthBadge}>{g.required_depth}</span>
      </div>

      {/* Prerequisite Concepts */}
      {g.prerequisite_concepts.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Prerequisite Concepts</div>
          <ul style={styles.bulletList}>
            {g.prerequisite_concepts.map((c, i) => (
              <li key={i} style={styles.bulletItem}>
                <span style={styles.bulletDot}>&bull;</span>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Common Misconceptions (from guidelines) */}
      {g.common_misconceptions.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Common Misconceptions</div>
          {g.common_misconceptions.map((m, i) => (
            <div key={i} style={styles.misconceptionCard}>
              {m}
            </div>
          ))}
        </div>
      )}

      {/* Detected Misconceptions (from session) */}
      {misconceptions.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            Detected Misconceptions ({misconceptions.length})
          </div>
          {misconceptions.map((m, i) => (
            <div key={i} style={styles.detectedMisconception(m.resolved)}>
              <div style={styles.detectedLabel(m.resolved)}>
                {m.resolved ? 'Resolved' : 'Unresolved'}
              </div>
              <div style={styles.detectedConcept}>{m.concept}</div>
              <div style={styles.detectedDesc}>{m.description}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
