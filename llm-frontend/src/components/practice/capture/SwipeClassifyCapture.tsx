import React, { useMemo, useState } from 'react';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps } from './types';

interface BucketItem {
  text: string;
}

/**
 * Swipe-classify — student sees one card at a time and picks one of two
 * categories. v1 uses tappable left/right buttons (no actual swipe
 * gestures) so the component works equally well on mobile + desktop.
 *
 * `value`: `number[]` with one bucket_idx (0 or 1) per item IN SERVED
 * ORDER. The deck is shuffled for display only; indexing stays stable.
 */
export default function SwipeClassifyCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<number[]>) {
  const bucketNames = (questionJson.bucket_names as string[] | undefined) ?? [];
  const items = (questionJson.bucket_items as BucketItem[] | undefined) ?? [];
  const deck = useMemo(
    () => seededShuffle(items.map((_, i) => i), seed),
    [items, seed],
  );
  const state: number[] = value ?? items.map(() => -1);

  const [cursor, setCursor] = useState(() =>
    deck.findIndex(origIdx => state[origIdx] === -1 || state[origIdx] === undefined),
  );

  const currentOrigIdx = cursor >= 0 ? deck[cursor] : -1;
  const current = currentOrigIdx >= 0 ? items[currentOrigIdx] : null;

  const classify = (bucketIdx: number) => {
    if (disabled || current === null) return;
    const next = state.slice();
    next[currentOrigIdx] = bucketIdx;
    onChange(next);
    const nextCursor = deck.findIndex((o, i) => i > cursor && (next[o] === -1 || next[o] === undefined));
    setCursor(nextCursor);
  };

  const classifiedCount = state.filter(v => v === 0 || v === 1).length;

  return (
    <div>
      <div className="practice-question-text">
        {questionJson.question_text as string}
      </div>

      <div className="practice-swipe-status">
        {classifiedCount} of {items.length} classified
      </div>

      {current ? (
        <>
          <div className="practice-swipe-card">{current.text}</div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              className="practice-swipe-btn"
              onClick={() => classify(0)}
              disabled={disabled}
            >
              ← {bucketNames[0]}
            </button>
            <button
              type="button"
              className="practice-swipe-btn"
              onClick={() => classify(1)}
              disabled={disabled}
            >
              {bucketNames[1]} →
            </button>
          </div>
        </>
      ) : (
        <div className="practice-swipe-empty">
          All items classified. Review your picks on the next screen.
        </div>
      )}

      {classifiedCount > 0 && (
        <div className="practice-swipe-undo">
          <div className="practice-swipe-undo-label">Tap to re-classify:</div>
          {items.map((it, i) => {
            const b = state[i];
            if (b !== 0 && b !== 1) return null;
            return (
              <button
                key={i}
                type="button"
                className="practice-swipe-undo-btn"
                onClick={() => {
                  if (disabled) return;
                  const next = state.slice();
                  next[i] = -1;
                  onChange(next);
                  const deckIdx = deck.indexOf(i);
                  if (deckIdx >= 0) setCursor(deckIdx);
                }}
                disabled={disabled}
              >
                {it.text} <span style={{ opacity: 0.6 }}>({bucketNames[b]})</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
