import React, { useMemo, useState } from 'react';
import PairColumn from '../../shared/PairColumn';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

/**
 * Match pairs — student taps a left item to activate, then taps a right
 * item to pair them. Tapping an already-paired left unpairs it.
 *
 * The backend-side `redact_for_student` replaced `pairs` with
 * `pair_lefts` + `pair_rights`. We preserve the left order (so the
 * student reads the prompt naturally) and shuffle rights via seed.
 *
 * Value shape: `{ [leftText]: rightText }`. Backend grading compares to
 * the unredacted snapshot's `pairs`.
 */
export default function MatchPairsCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<Record<string, string>>) {
  const lefts = (questionJson.pair_lefts as string[] | undefined) ?? [];
  const rightsRaw = (questionJson.pair_rights as string[] | undefined) ?? [];
  const rights = useMemo(() => seededShuffle(rightsRaw, seed), [rightsRaw, seed]);

  const [activeLeft, setActiveLeft] = useState<string | null>(null);
  const pairs = value ?? {};

  const onLeftClick = (left: string) => {
    if (pairs[left]) {
      const next = { ...pairs };
      delete next[left];
      onChange(next);
      setActiveLeft(null);
      return;
    }
    setActiveLeft(left === activeLeft ? null : left);
  };

  const onRightClick = (right: string) => {
    if (!activeLeft) return;
    const next = { ...pairs };
    for (const k of Object.keys(next)) {
      if (next[k] === right) delete next[k];
    }
    next[activeLeft] = right;
    onChange(next);
    setActiveLeft(null);
  };

  const usedRights = Object.values(pairs);
  const usedLefts = Object.keys(pairs);

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>
      <div className="practice-subhint">
        Tap a term on the left, then tap its match on the right.
      </div>
      <div className="practice-pair-row">
        <PairColumn
          title="Terms"
          items={lefts}
          activeItem={activeLeft}
          usedItems={usedLefts}
          onItemClick={onLeftClick}
          disabled={disabled}
        />
        <PairColumn
          title="Matches"
          items={rights}
          activeItem={null}
          usedItems={usedRights}
          onItemClick={onRightClick}
          disabled={disabled || activeLeft === null}
        />
      </div>
      {Object.keys(pairs).length > 0 && (
        <div className="practice-pair-summary">
          <strong>Your pairs:</strong>{' '}
          {Object.entries(pairs).map(([l, r]) => `${l} ↔ ${r}`).join(', ')}
        </div>
      )}
    </div>
  );
}
