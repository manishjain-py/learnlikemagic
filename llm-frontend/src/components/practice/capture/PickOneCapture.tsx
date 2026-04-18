import React, { useMemo } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Single best answer from N options. Displays options in a seed-shuffled
 * order but stores the ORIGINAL index as `value` so grading works.
 */
export default function PickOneCapture({
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
