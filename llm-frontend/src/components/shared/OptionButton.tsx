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
 * The only visual states are: idle, selected, eliminated, disabled.
 */
export default function OptionButton({
  label, selected, onClick, disabled, eliminated,
}: Props) {
  return (
    <button
      type="button"
      onClick={() => { if (!disabled && !eliminated) onClick(); }}
      disabled={disabled}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        padding: '12px 16px',
        marginBottom: '8px',
        borderRadius: '10px',
        border: selected ? '2px solid #0891B2' : '2px solid #E5E7EB',
        backgroundColor: selected ? '#CCFBF1' : eliminated ? '#F3F4F6' : 'white',
        color: eliminated ? '#9CA3AF' : '#111827',
        fontSize: '15px',
        fontWeight: 500,
        cursor: disabled || eliminated ? 'default' : 'pointer',
        textDecoration: eliminated ? 'line-through' : 'none',
        opacity: disabled ? 0.6 : 1,
        transition: 'border-color 120ms ease, background-color 120ms ease',
      }}
    >
      {label}
    </button>
  );
}
