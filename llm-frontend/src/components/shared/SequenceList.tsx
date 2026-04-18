import React from 'react';

interface Props {
  /** Items in their current student-ordered sequence. */
  items: string[];
  /** Called with a new ordering. */
  onReorder: (next: string[]) => void;
  disabled?: boolean;
}

/**
 * Reorderable list for SequenceCapture. Controlled — no internal state.
 * Up / Down buttons per row; simpler than drag-drop and accessible on
 * mobile without requiring pointer events.
 */
export default function SequenceList({ items, onReorder, disabled }: Props) {
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= items.length) return;
    const next = items.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onReorder(next);
  };

  return (
    <div>
      {items.map((item, i) => (
        <div key={item} className="practice-seq-row">
          <span className="practice-seq-num">{i + 1}</span>
          <span className="practice-seq-text">{item}</span>
          <button
            type="button"
            className="practice-seq-arrow"
            onClick={() => move(i, -1)}
            disabled={disabled || i === 0}
          >
            ↑
          </button>
          <button
            type="button"
            className="practice-seq-arrow"
            onClick={() => move(i, 1)}
            disabled={disabled || i === items.length - 1}
          >
            ↓
          </button>
        </div>
      ))}
    </div>
  );
}
