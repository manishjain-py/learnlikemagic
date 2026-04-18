import React from 'react';
import { CaptureProps } from './types';

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
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      <div className="practice-subhint">Tap the step that has a mistake.</div>
      {steps.map((step, i) => {
        const cls = ['practice-step-row', value === i && 'selected']
          .filter(Boolean).join(' ');
        return (
          <button
            key={i}
            type="button"
            className={cls}
            onClick={() => { if (!disabled) onChange(i); }}
            disabled={disabled}
          >
            <span className="practice-step-num">{i + 1}</span>
            <span>{step}</span>
          </button>
        );
      })}
    </div>
  );
}
