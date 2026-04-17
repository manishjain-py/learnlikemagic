import React, { useMemo } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Pick the item that doesn't belong. Items shuffled by seed; stored value
 * is the original index.
 */
export default function OddOneOutCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<number>) {
  const items = (questionJson.odd_items as string[] | undefined) ?? [];
  const displayOrder = useMemo(
    () => seededShuffle(items.map((_, i) => i), seed),
    [items, seed],
  );

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      <div className="practice-subhint">Which one doesn't belong?</div>
      {displayOrder.map(origIdx => (
        <OptionButton
          key={origIdx}
          label={items[origIdx]}
          selected={value === origIdx}
          onClick={() => onChange(origIdx)}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
