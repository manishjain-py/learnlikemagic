import React, { useMemo } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Predict-then-reveal: student predicts an outcome from a set of options.
 * The reveal phase (showing the correct answer + explanation) belongs to
 * the results/review page — `reveal_text` is redacted during the set.
 *
 * Behaves identically to pick_one at capture time.
 */
export default function PredictThenRevealCapture({
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
      <div className="practice-subhint">What do you think will happen?</div>
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
