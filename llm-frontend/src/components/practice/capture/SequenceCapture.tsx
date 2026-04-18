import React, { useEffect } from 'react';
import SequenceList from '../../shared/SequenceList';
import { CaptureProps } from './types';

/**
 * Put items in the correct order. The server shuffles `sequence_items`
 * via `_presentation_seed` before serving so the raw payload doesn't
 * leak the correct order; this component just displays what it receives.
 *
 * On mount, if the student has no prior answer, we register the received
 * order as the initial answer so a student who never drags isn't graded
 * blank on an order that might coincidentally be correct.
 *
 * Grading compares `string[]` equality against the snapshot's original
 * (unredacted) `sequence_items`.
 */
export default function SequenceCapture({
  questionJson, value, onChange, disabled,
}: CaptureProps<string[]>) {
  const initialOrder = (questionJson.sequence_items as string[] | undefined) ?? [];
  const current = value ?? initialOrder;

  // Register the initial display order as the student's answer on mount.
  // Only fires when value is null (un-submitted); subsequent reorders are
  // driven by SequenceList's onReorder.
  useEffect(() => {
    if (!disabled && value == null && initialOrder.length > 0) {
      onChange(initialOrder);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
