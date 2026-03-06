import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { VisualExplanation as VisualExplanationType, VisualRow } from '../api';

interface Props {
  visual: VisualExplanationType;
}

// Color palette
const COLORS = {
  heading: '#1E293B',
  label: '#475569',
  result: '#22C55E',
  caption: '#64748B',
  barFill: '#4F9CF7',
  barEmpty: '#E2E8F0',
  arrow: '#94A3B8',
  divider: '#E2E8F0',
};

export default function VisualExplanation({ visual }: Props) {
  const [started, setStarted] = useState(false);
  const [visibleRows, setVisibleRows] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const totalRows = visual.rows.length;

  const advance = useCallback(() => {
    setVisibleRows((v) => {
      if (v >= totalRows) {
        setIsPlaying(false);
        return v;
      }
      return v + 1;
    });
  }, [totalRows]);

  useEffect(() => {
    if (!isPlaying) return;
    const delay = visibleRows < totalRows
      ? (visual.rows[visibleRows]?.delay_ms ?? 600)
      : 0;
    timerRef.current = setTimeout(advance, delay);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [visibleRows, isPlaying, advance, visual, totalRows]);

  const startAnimation = () => {
    setVisibleRows(0);
    setStarted(true);
    setIsPlaying(true);
  };

  const replay = () => {
    setVisibleRows(0);
    setIsPlaying(true);
  };

  if (!started) {
    return (
      <div className="visual-explanation visual-explanation--collapsed">
        <button className="visual-start-btn" onClick={startAnimation}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none" />
          </svg>
          {visual.title ? `Visualise: ${visual.title}` : 'Visualise'}
        </button>
      </div>
    );
  }

  return (
    <div className="visual-explanation">
      {visual.title && <div className="visual-title">{visual.title}</div>}
      <div className="visual-canvas">
        {visual.rows.slice(0, visibleRows).map((row, i) => (
          <div key={i} className="visual-row visual-fade-in">
            {renderRow(row)}
          </div>
        ))}
      </div>
      {visual.narration && visibleRows >= totalRows && (
        <div className="visual-narration">{visual.narration}</div>
      )}
      <button className="visual-replay-btn" onClick={replay} title="Replay animation">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="1 4 1 10 7 10" />
          <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
        </svg>
        Replay
      </button>
    </div>
  );
}

function renderRow(row: VisualRow): React.ReactNode {
  switch (row.type) {
    case 'emoji_group':
      return renderEmojiGroup(row);
    case 'text':
      return renderText(row);
    case 'arrow':
      return renderArrow(row);
    case 'divider':
      return <div className="visual-divider" />;
    case 'columns':
      return renderColumns(row);
    case 'fraction_bar':
      return renderFractionBar(row);
    default:
      return null;
  }
}

function renderEmojiGroup(row: VisualRow) {
  const emoji = row.emoji || '⭐';
  const count = row.count || 1;
  return (
    <div className="visual-emoji-group">
      {Array.from({ length: count }).map((_, i) => (
        <span key={i} className="visual-emoji-item visual-pop-in">{emoji}</span>
      ))}
    </div>
  );
}

function renderText(row: VisualRow) {
  const style = row.style || 'label';
  const color = row.color;
  const className = `visual-text visual-text--${style}`;
  return (
    <div className={className} style={color ? { color } : undefined}>
      {row.text}
    </div>
  );
}

function renderArrow(row: VisualRow) {
  return (
    <div className="visual-arrow">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={COLORS.arrow} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="5" x2="12" y2="19" />
        <polyline points="19 12 12 19 5 12" />
      </svg>
      {row.text && <span className="visual-arrow-label">{row.text}</span>}
    </div>
  );
}

function renderColumns(row: VisualRow) {
  if (!row.columns || row.columns.length === 0) return null;
  return (
    <div className="visual-columns">
      {row.columns.map((col, i) => (
        <div key={i} className="visual-column">
          {renderRow(col)}
        </div>
      ))}
    </div>
  );
}

function renderFractionBar(row: VisualRow) {
  const total = row.total_parts || 4;
  const highlighted = row.highlighted_parts || 0;
  const label = row.fraction_label;
  return (
    <div className="visual-fraction">
      <div className="visual-fraction-bar">
        {Array.from({ length: total }).map((_, i) => (
          <div
            key={i}
            className={`visual-fraction-part ${i < highlighted ? 'visual-fraction-part--filled' : ''}`}
          />
        ))}
      </div>
      {label && <div className="visual-fraction-label">{label}</div>}
    </div>
  );
}
