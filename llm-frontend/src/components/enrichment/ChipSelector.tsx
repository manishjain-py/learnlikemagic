/**
 * ChipSelector — Reusable multi-select chip component.
 * Used by Sections 1, 3, 4, 5, 6 for tag-based selection.
 */

import React, { useState } from 'react';

interface ChipSelectorProps {
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
  allowCustom?: boolean;
}

export default function ChipSelector({ options, selected, onChange, allowCustom = false }: ChipSelectorProps) {
  const [customInput, setCustomInput] = useState('');
  const [showCustom, setShowCustom] = useState(false);

  const toggle = (option: string) => {
    if (selected.includes(option)) {
      onChange(selected.filter((s) => s !== option));
    } else {
      onChange([...selected, option]);
    }
  };

  const addCustom = () => {
    const trimmed = customInput.trim();
    if (trimmed && !selected.includes(trimmed)) {
      onChange([...selected, trimmed]);
    }
    setCustomInput('');
    setShowCustom(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addCustom();
    }
  };

  // Merge options + any custom items that aren't in the predefined list
  const allOptions = [...options, ...selected.filter((s) => !options.includes(s))];

  return (
    <div className="enrichment-chips">
      {allOptions.map((option) => (
        <button
          key={option}
          type="button"
          className={`enrichment-chip ${selected.includes(option) ? 'enrichment-chip-selected' : ''}`}
          onClick={() => toggle(option)}
        >
          {option}
        </button>
      ))}
      {allowCustom && !showCustom && (
        <button
          type="button"
          className="enrichment-chip enrichment-chip-add"
          onClick={() => setShowCustom(true)}
        >
          + Add your own
        </button>
      )}
      {allowCustom && showCustom && (
        <div className="enrichment-chip-custom">
          <input
            type="text"
            value={customInput}
            onChange={(e) => setCustomInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={addCustom}
            placeholder="Type and press Enter"
            maxLength={50}
            autoFocus
          />
        </div>
      )}
    </div>
  );
}
