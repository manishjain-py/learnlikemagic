/**
 * SessionPreferences — Attention span + pace preference.
 */

import React from 'react';

interface SessionPreferencesProps {
  attentionSpan: string;
  pacePreference: string;
  onChange: (field: string, value: string) => void;
}

const ATTENTION_OPTIONS = [
  { value: 'short', label: 'Short (10-15 min)' },
  { value: 'medium', label: 'Medium (15-25 min)' },
  { value: 'long', label: 'Long (25+ min)' },
];

const PACE_OPTIONS = [
  { value: 'slow', label: 'Slow and thorough' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'fast', label: 'Fast-paced' },
];

export default function SessionPreferences({ attentionSpan, pacePreference, onChange }: SessionPreferencesProps) {
  return (
    <div className="enrichment-session-prefs">
      <div className="auth-field">
        <label>Attention span</label>
        <div className="enrichment-chips">
          {ATTENTION_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`enrichment-chip ${attentionSpan === opt.value ? 'enrichment-chip-selected' : ''}`}
              onClick={() => onChange('attention_span', opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="auth-field">
        <label>Pace preference</label>
        <div className="enrichment-chips">
          {PACE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`enrichment-chip ${pacePreference === opt.value ? 'enrichment-chip-selected' : ''}`}
              onClick={() => onChange('pace_preference', opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
