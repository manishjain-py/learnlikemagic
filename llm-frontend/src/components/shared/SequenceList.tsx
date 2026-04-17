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
        <div
          key={`${i}:${item}`}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 12px', marginBottom: '6px',
            border: '1px solid #E5E7EB', borderRadius: '8px',
            backgroundColor: 'white', fontSize: '14px',
          }}
        >
          <span style={{
            width: '28px', height: '28px', borderRadius: '14px',
            backgroundColor: '#F3F4F6', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: '12px', fontWeight: 700, color: '#6B7280',
          }}>
            {i + 1}
          </span>
          <span style={{ flex: 1, color: '#111827' }}>{item}</span>
          <button
            type="button" onClick={() => move(i, -1)}
            disabled={disabled || i === 0}
            style={navBtnStyle(disabled || i === 0)}
          >
            ↑
          </button>
          <button
            type="button" onClick={() => move(i, 1)}
            disabled={disabled || i === items.length - 1}
            style={navBtnStyle(disabled || i === items.length - 1)}
          >
            ↓
          </button>
        </div>
      ))}
    </div>
  );
}

function navBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    width: '32px', height: '32px', borderRadius: '6px',
    border: '1px solid #E5E7EB', backgroundColor: disabled ? '#F9FAFB' : 'white',
    color: disabled ? '#D1D5DB' : '#374151',
    cursor: disabled ? 'default' : 'pointer', fontSize: '15px',
  };
}
