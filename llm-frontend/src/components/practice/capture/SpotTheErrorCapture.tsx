import React from 'react';
import { CaptureProps, QUESTION_TEXT_STYLE } from './types';

/**
 * Student picks which step in a sequence contains the error. Steps are
 * shown in their original order (the step index IS the answer) so this
 * component does NOT seed-shuffle — the numbering must match.
 */
export default function SpotTheErrorCapture({
  questionJson, value, onChange, disabled,
}: CaptureProps<number>) {
  const steps = (questionJson.error_steps as string[] | undefined) ?? [];

  return (
    <div>
      <div style={QUESTION_TEXT_STYLE}>
        {questionJson.question_text as string}
      </div>
      <div style={{
        fontSize: '12px', color: '#6B7280', marginBottom: '12px',
        fontStyle: 'italic',
      }}>
        Tap the step that has a mistake.
      </div>
      {steps.map((step, i) => (
        <button
          key={i}
          type="button"
          onClick={() => { if (!disabled) onChange(i); }}
          disabled={disabled}
          style={{
            display: 'flex', alignItems: 'flex-start', gap: '10px',
            width: '100%', textAlign: 'left',
            padding: '12px 14px', marginBottom: '8px',
            borderRadius: '10px',
            border: value === i ? '2px solid #0891B2' : '2px solid #E5E7EB',
            backgroundColor: value === i ? '#CCFBF1' : 'white',
            color: '#111827',
            cursor: disabled ? 'default' : 'pointer',
            opacity: disabled ? 0.6 : 1,
          }}
        >
          <span style={{
            width: '26px', height: '26px', borderRadius: '13px',
            backgroundColor: '#F3F4F6', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: '12px', fontWeight: 700, color: '#6B7280', flexShrink: 0,
          }}>
            {i + 1}
          </span>
          <span style={{ fontSize: '14px', lineHeight: 1.4 }}>{step}</span>
        </button>
      ))}
    </div>
  );
}
