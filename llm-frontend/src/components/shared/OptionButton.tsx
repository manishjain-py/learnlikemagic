import React from 'react';

interface Props {
  label: string;
  selected: boolean;
  onClick: () => void;
  disabled?: boolean;
  /** Render as crossed-out (tap_to_eliminate's already-eliminated state). */
  eliminated?: boolean;
}

/**
 * Single selectable option button. Controlled — no internal correctness state.
 * Styling driven by `.practice-option` CSS under `.chalkboard-active`.
 */
export default function OptionButton({
  label, selected, onClick, disabled, eliminated,
}: Props) {
  const cls = [
    'practice-option',
    selected && 'selected',
    eliminated && 'eliminated',
  ].filter(Boolean).join(' ');
  return (
    <button
      type="button"
      className={cls}
      onClick={() => { if (!disabled && !eliminated) onClick(); }}
      disabled={disabled}
    >
      {label}
    </button>
  );
}
