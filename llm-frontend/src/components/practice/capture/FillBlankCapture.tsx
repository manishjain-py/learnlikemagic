import React, { useMemo } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Fill-the-blank — visually identical to PickOneCapture but the question
 * text typically contains an explicit blank marker (e.g. "___"). Shuffle
 * order is seed-stable; stored value is the original index.
 */
export default function FillBlankCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<number>) {
  const options = (questionJson.options as string[] | undefined) ?? [];
  const displayOrder = useMemo(
    () => seededShuffle(options.map((_, i) => i), seed),
    [options, seed],
  );

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      {displayOrder.map(origIdx => (
        <OptionButton
          key={origIdx}
          label={options[origIdx]}
          selected={value === origIdx}
          onClick={() => onChange(origIdx)}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
