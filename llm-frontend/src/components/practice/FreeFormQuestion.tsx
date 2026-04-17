import React from 'react';

interface Props {
  questionJson: Record<string, unknown>;
  value: string | null;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * Free-form answer — parchment textarea on the chalkboard. No correctness
 * styling: the LLM grader reads this at submit time.
 */
export default function FreeFormQuestion({
  questionJson, value, onChange, disabled,
}: Props) {
  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      <div className="practice-subhint">
        Type your answer below. Show your steps if you can.
      </div>
      <textarea
        className="practice-freeform-textarea"
        value={value ?? ''}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        rows={5}
        placeholder="Type here..."
      />
    </div>
  );
}
