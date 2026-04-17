import React from 'react';

interface Props {
  items: string[];
  /** The currently highlighted item (picker state), or null. */
  activeItem: string | null;
  /** Items already used in a pair. Shown muted. */
  usedItems: string[];
  onItemClick: (item: string) => void;
  disabled?: boolean;
  title?: string;
}

/**
 * Vertical column used by MatchPairsCapture. Student taps a left item to
 * activate it, then taps a right item to form the pair. Items already in
 * a pair are rendered muted — the parent may still allow re-selection to
 * unmatch.
 */
export default function PairColumn({
  items, activeItem, usedItems, onItemClick, disabled, title,
}: Props) {
  return (
    <div style={{ flex: 1 }}>
      {title && (
        <div style={{
          fontSize: '12px', fontWeight: 600, textTransform: 'uppercase',
          color: '#6B7280', marginBottom: '8px', letterSpacing: '0.5px',
        }}>
          {title}
        </div>
      )}
      {items.map(item => {
        const isActive = activeItem === item;
        const isUsed = usedItems.includes(item);
        return (
          <button
            key={item}
            type="button"
            onClick={() => { if (!disabled) onItemClick(item); }}
            disabled={disabled}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '10px 14px',
              marginBottom: '6px',
              borderRadius: '8px',
              border: isActive ? '2px solid #0891B2' : '2px solid #E5E7EB',
              backgroundColor: isActive
                ? '#CCFBF1'
                : isUsed ? '#F3F4F6' : 'white',
              color: isUsed && !isActive ? '#9CA3AF' : '#111827',
              fontSize: '14px',
              cursor: disabled ? 'default' : 'pointer',
              opacity: disabled ? 0.6 : 1,
            }}
          >
            {item}
          </button>
        );
      })}
    </div>
  );
}
