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
    <div className="practice-pair-col">
      {title && <div className="practice-pair-col-title">{title}</div>}
      {items.map(item => {
        const isActive = activeItem === item;
        const isUsed = usedItems.includes(item);
        const cls = [
          'practice-pair-item',
          isActive && 'active',
          isUsed && !isActive && 'used',
        ].filter(Boolean).join(' ');
        return (
          <button
            key={item}
            type="button"
            className={cls}
            onClick={() => { if (!disabled) onItemClick(item); }}
            disabled={disabled}
          >
            {item}
          </button>
        );
      })}
    </div>
  );
}
