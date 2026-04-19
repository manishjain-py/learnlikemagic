/**
 * QualitySelector — popover UI for Fast / Balanced / Thorough.
 *
 * Maps to per-stage review_rounds on the backend:
 *   fast      → 0/0/0/0
 *   balanced  → 2/1/1/2
 *   thorough  → 3/2/2/3
 */
import React, { useEffect, useRef } from 'react';
import type { QualityLevel } from '../api/adminApiV2';

interface QualityOption {
  level: QualityLevel;
  title: string;
  subtitle: string;
  rounds: string;
}

const OPTIONS: QualityOption[] = [
  {
    level: 'fast',
    title: 'Fast',
    subtitle: 'Initial generation only, no review-refine rounds.',
    rounds: '0 / 0 / 0 / 0',
  },
  {
    level: 'balanced',
    title: 'Balanced',
    subtitle: 'Moderate review-refine. Default.',
    rounds: '2 / 1 / 1 / 2',
  },
  {
    level: 'thorough',
    title: 'Thorough',
    subtitle: 'Maximum review-refine. Slower.',
    rounds: '3 / 2 / 2 / 3',
  },
];

interface QualitySelectorProps {
  open: boolean;
  onClose: () => void;
  onPick: (level: QualityLevel) => void;
  defaultLevel?: QualityLevel;
  force?: boolean;
  onForceChange?: (next: boolean) => void;
}

const QualitySelector: React.FC<QualitySelectorProps> = ({
  open,
  onClose,
  onPick,
  defaultLevel = 'balanced',
  force = false,
  onForceChange,
}) => {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('keydown', esc);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={ref}
      style={{
        position: 'absolute',
        right: 0,
        top: 44,
        zIndex: 20,
        width: 320,
        backgroundColor: 'white',
        border: '1px solid #E5E7EB',
        borderRadius: 8,
        boxShadow: '0 10px 24px rgba(0,0,0,0.12)',
        padding: 10,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: '#6B7280',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          padding: '4px 6px',
        }}
      >
        Quality (expl / vis / chk / prac rounds)
      </div>
      {OPTIONS.map((opt) => (
        <button
          key={opt.level}
          type="button"
          onClick={() => onPick(opt.level)}
          style={{
            width: '100%',
            textAlign: 'left',
            padding: '10px 10px',
            borderRadius: 6,
            border: 'none',
            backgroundColor:
              opt.level === defaultLevel ? '#EEF2FF' : 'transparent',
            cursor: 'pointer',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F9FAFB')}
          onMouseLeave={(e) =>
            (e.currentTarget.style.backgroundColor =
              opt.level === defaultLevel ? '#EEF2FF' : 'transparent')
          }
        >
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: '#111827' }}>
              {opt.title}
            </span>
            <span style={{ fontSize: 11, color: '#6B7280', fontFamily: 'monospace' }}>
              {opt.rounds}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#4B5563', marginTop: 2 }}>
            {opt.subtitle}
          </div>
        </button>
      ))}

      {onForceChange && (
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 8px 4px',
            borderTop: '1px solid #E5E7EB',
            marginTop: 6,
            fontSize: 12,
            color: '#374151',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => onForceChange(e.target.checked)}
          />
          Force re-run stages already marked Done
        </label>
      )}
    </div>
  );
};

export default QualitySelector;
