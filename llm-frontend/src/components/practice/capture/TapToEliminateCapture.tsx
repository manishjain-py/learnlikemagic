import React, { useMemo, useState } from 'react';
import OptionButton from '../../shared/OptionButton';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps, QUESTION_TEXT_STYLE } from './types';

/**
 * Tap to eliminate — student crosses out wrong options first, then picks.
 *
 * `value` is the final chosen index (matches pick_one's shape) so grading
 * is identical. The eliminated set is local-only state; it doesn't need
 * to survive a page reload because the student can re-eliminate in a
 * fresh session and the answer they ultimately select is what grades.
 *
 * Interaction: one tap on an option selects it. A small "✕" in the
 * option's row eliminates it (crossed out, untappable).
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
      if (value === idx) onChange(-1 as number); // de-select if eliminating current pick
    }
    setEliminated(next);
  };

  return (
    <div>
      <div style={QUESTION_TEXT_STYLE}>
        {questionJson.question_text as string}
      </div>
      {displayOrder.map(origIdx => (
        <div key={origIdx} style={{ display: 'flex', gap: '8px', alignItems: 'stretch' }}>
          <div style={{ flex: 1 }}>
            <OptionButton
              label={options[origIdx]}
              selected={value === origIdx}
              onClick={() => onChange(origIdx)}
              disabled={disabled}
              eliminated={eliminated.has(origIdx)}
            />
          </div>
          <button
            type="button"
            onClick={() => toggleEliminate(origIdx)}
            disabled={disabled}
            title={eliminated.has(origIdx) ? 'Undo eliminate' : 'Eliminate'}
            style={{
              width: '44px', marginBottom: '8px', borderRadius: '10px',
              border: '2px solid #E5E7EB',
              backgroundColor: eliminated.has(origIdx) ? '#FEE2E2' : 'white',
              color: eliminated.has(origIdx) ? '#991B1B' : '#6B7280',
              cursor: disabled ? 'default' : 'pointer',
              fontSize: '15px', fontWeight: 700,
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
