import React, { useMemo, useState } from 'react';
import BucketZone from '../../shared/BucketZone';
import { seededShuffle } from '../../shared/seededShuffle';
import { CaptureProps, QUESTION_TEXT_STYLE } from './types';

interface BucketItem {
  text: string;
}

/**
 * Sort items into one of two buckets. Student selects an item (tap) then
 * taps a bucket to place it. Re-tapping an item in a bucket un-assigns it.
 *
 * `value` shape: `number[]` with one bucket_idx (0 or 1) per item IN THE
 * ORDER SERVED (stable — we don't shuffle bucket_items). Unassigned items
 * are represented by -1 internally; the value returned to the parent
 * preserves partial state for round-tripping.
 */
export default function SortBucketsCapture({
  questionJson, value, onChange, seed, disabled,
}: CaptureProps<number[]>) {
  const bucketNames = (questionJson.bucket_names as string[] | undefined) ?? [];
  const items = (questionJson.bucket_items as BucketItem[] | undefined) ?? [];
  // Items are shown in a seed-shuffled DISPLAY order but value indexing
  // follows the original served order so grading works.
  const displayOrder = useMemo(
    () => seededShuffle(items.map((_, i) => i), seed),
    [items, seed],
  );

  const state: number[] = value ?? items.map(() => -1);
  const [active, setActive] = useState<number | null>(null);

  const onItemClick = (origIdx: number) => {
    if (disabled) return;
    setActive(active === origIdx ? null : origIdx);
  };

  const onBucketClick = (bucketIdx: number) => {
    if (disabled || active === null) return;
    const next = state.slice();
    next[active] = bucketIdx;
    onChange(next);
    setActive(null);
  };

  return (
    <div>
      <div style={QUESTION_TEXT_STYLE}>
        {questionJson.question_text as string}
      </div>
      <div style={{
        fontSize: '12px', color: '#6B7280', marginBottom: '12px',
        fontStyle: 'italic',
      }}>
        Tap an item below, then tap its bucket.
      </div>

      {/* Items not yet assigned */}
      <div style={{ marginBottom: '14px' }}>
        {displayOrder.map(origIdx => {
          const assigned = state[origIdx] !== -1 && state[origIdx] !== undefined;
          if (assigned) return null;
          return (
            <button
              key={origIdx}
              type="button"
              onClick={() => onItemClick(origIdx)}
              disabled={disabled}
              style={{
                display: 'inline-block',
                padding: '8px 12px', margin: '4px',
                borderRadius: '8px',
                border: active === origIdx ? '2px solid #0891B2' : '2px solid #E5E7EB',
                backgroundColor: active === origIdx ? '#CCFBF1' : 'white',
                fontSize: '13px', color: '#111827',
                cursor: disabled ? 'default' : 'pointer',
              }}
            >
              {items[origIdx].text}
            </button>
          );
        })}
      </div>

      {/* Bucket drop zones */}
      <div style={{ display: 'flex', gap: '10px' }}>
        {bucketNames.map((name, bIdx) => {
          const itemsInBucket = state
            .map((b, i) => ({ b, i }))
            .filter(({ b }) => b === bIdx)
            .map(({ i }) => items[i].text);
          return (
            <BucketZone
              key={bIdx}
              name={name}
              itemsInBucket={itemsInBucket}
              onDrop={active !== null ? () => onBucketClick(bIdx) : undefined}
              active={active !== null}
              disabled={disabled}
            />
          );
        })}
      </div>
    </div>
  );
}
