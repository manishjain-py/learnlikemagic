import React, { useMemo, useState } from 'react';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps, QUESTION_TEXT_STYLE } from './types';

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

  // Index into `deck` pointing at the next unanswered card.
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
    // Advance to next unanswered card.
    const nextCursor = deck.findIndex((o, i) => i > cursor && (next[o] === -1 || next[o] === undefined));
    setCursor(nextCursor);
  };

  const classifiedCount = state.filter(v => v === 0 || v === 1).length;

  return (
    <div>
      <div style={QUESTION_TEXT_STYLE}>
        {questionJson.question_text as string}
      </div>

      <div style={{
        fontSize: '12px', color: '#6B7280', marginBottom: '12px',
        textAlign: 'center',
      }}>
        {classifiedCount} of {items.length} classified
      </div>

      {current ? (
        <>
          <div style={{
            padding: '24px 16px', marginBottom: '16px',
            backgroundColor: 'white', borderRadius: '12px',
            border: '2px solid #E5E7EB',
            fontSize: '18px', fontWeight: 500, color: '#111827',
            textAlign: 'center', minHeight: '80px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {current.text}
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              onClick={() => classify(0)}
              disabled={disabled}
              style={swipeBtnStyle('#0891B2', disabled)}
            >
              ← {bucketNames[0]}
            </button>
            <button
              type="button"
              onClick={() => classify(1)}
              disabled={disabled}
              style={swipeBtnStyle('#7C3AED', disabled)}
            >
              {bucketNames[1]} →
            </button>
          </div>
        </>
      ) : (
        <div style={{
          padding: '24px 16px', textAlign: 'center',
          color: '#065F46', fontSize: '14px',
          backgroundColor: '#D1FAE5', borderRadius: '12px',
        }}>
          All items classified. Review your picks on the next screen.
        </div>
      )}

      {/* Compact undo bar — tap a classified item to return it to the deck. */}
      {classifiedCount > 0 && (
        <div style={{
          marginTop: '14px', padding: '8px',
          backgroundColor: '#F9FAFB', borderRadius: '8px',
          fontSize: '11px', color: '#6B7280',
        }}>
          <div style={{ marginBottom: '6px', fontWeight: 600 }}>Tap to re-classify:</div>
          {items.map((it, i) => {
            const b = state[i];
            if (b !== 0 && b !== 1) return null;
            return (
              <button
                key={i}
                type="button"
                onClick={() => {
                  if (disabled) return;
                  const next = state.slice();
                  next[i] = -1;
                  onChange(next);
                  // Point the cursor at this card.
                  const deckIdx = deck.indexOf(i);
                  if (deckIdx >= 0) setCursor(deckIdx);
                }}
                disabled={disabled}
                style={{
                  display: 'inline-block', margin: '3px',
                  padding: '4px 10px', borderRadius: '6px',
                  border: '1px solid #D1D5DB',
                  backgroundColor: 'white',
                  fontSize: '11px', color: '#374151',
                  cursor: disabled ? 'default' : 'pointer',
                }}
              >
                {it.text} <span style={{ color: '#9CA3AF' }}>({bucketNames[b]})</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function swipeBtnStyle(color: string, disabled?: boolean): React.CSSProperties {
  return {
    flex: 1, padding: '14px', borderRadius: '10px',
    border: 'none', backgroundColor: color, color: 'white',
    fontSize: '14px', fontWeight: 600,
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.6 : 1,
  };
}
