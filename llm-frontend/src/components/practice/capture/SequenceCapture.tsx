import React, { useMemo } from 'react';
import SequenceList from '../../shared/SequenceList';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Put items in the correct order. The initial display is a seed-shuffled
 * copy of the original `sequence_items`. Value is the reordered array.
 *
 * Note: the value stored is a `string[]` of the current sequence, NOT an
 * index permutation. Backend grading compares directly against the
 * snapshot's `sequence_items`.
 */
export default function SequenceCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<string[]>) {
  const original = (questionJson.sequence_items as string[] | undefined) ?? [];
  const initialOrder = useMemo(() => seededShuffle(original, seed), [original, seed]);
  const current = value ?? initialOrder;

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      <div className="practice-subhint">Use ↑ ↓ to put these in the correct order.</div>
      <SequenceList items={current} onReorder={onChange} disabled={disabled} />
    </div>
  );
}
