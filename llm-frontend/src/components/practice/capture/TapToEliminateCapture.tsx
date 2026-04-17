import React, { useMemo, useState } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Tap to eliminate — student crosses out wrong options first, then picks.
 *
 * `value` is the final chosen index (matches pick_one's shape) so grading
 * is identical. The eliminated set is local-only state; it doesn't need
 * to survive a page reload because the student can re-eliminate in a
 * fresh session and the answer they ultimately select is what grades.
 */
export default function TapToEliminateCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<number>) {
  const options = (questionJson.options as string[] | undefined) ?? [];
  const [eliminated, setEliminated] = useState<Set<number>>(new Set());
  const displayOrder = useMemo(
    () => seededShuffle(options.map((_, i) => i), seed),
    [options, seed],
  );

  const toggleEliminate = (idx: number) => {
    if (disabled) return;
    const next = new Set(eliminated);
    if (next.has(idx)) next.delete(idx);
    else {
      next.add(idx);
      if (value === idx) onChange(-1 as number);
    }
    setEliminated(next);
  };

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      {displayOrder.map(origIdx => {
        const isElim = eliminated.has(origIdx);
        return (
          <div key={origIdx} style={{ display: 'flex', gap: '8px', alignItems: 'stretch' }}>
            <div style={{ flex: 1 }}>
              <OptionButton
                label={options[origIdx]}
                selected={value === origIdx}
                onClick={() => onChange(origIdx)}
                disabled={disabled}
                eliminated={isElim}
              />
            </div>
            <button
              type="button"
              className={['practice-eliminate-btn', isElim && 'active'].filter(Boolean).join(' ')}
              onClick={() => toggleEliminate(origIdx)}
              disabled={disabled}
              title={isElim ? 'Undo eliminate' : 'Eliminate'}
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
