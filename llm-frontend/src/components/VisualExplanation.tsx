import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { VisualExplanation as VisualExplanationType } from '../api';

interface Props {
  visual: VisualExplanationType;
}

// Default emoji for objects
const DEFAULT_EMOJI = '\u2B50';

// Color palette for kid-friendly visuals
const COLORS = {
  group1: '#4F9CF7',   // blue
  group2: '#F97316',   // orange
  result: '#22C55E',   // green
  highlight: '#8B5CF6', // purple
  bar: '#E2E8F0',      // light gray
  barFill: '#4F9CF7',  // blue
  text: '#1E293B',     // dark
  narration: '#475569', // medium gray
};

export default function VisualExplanation({ visual }: Props) {
  const [started, setStarted] = useState(false);
  const [phase, setPhase] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const totalPhases = getTotalPhases(visual);

  const advance = useCallback(() => {
    setPhase((p) => {
      if (p >= totalPhases - 1) {
        setIsPlaying(false);
        return p;
      }
      return p + 1;
    });
  }, [totalPhases]);

  useEffect(() => {
    if (!isPlaying) return;
    timerRef.current = setTimeout(advance, getDelay(visual, phase));
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [phase, isPlaying, advance, visual]);

  const startAnimation = () => {
    setPhase(0);
    setStarted(true);
    setIsPlaying(true);
  };

  const replay = () => {
    setPhase(0);
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
        {renderScene(visual, phase)}
      </div>
      {visual.narration && phase >= totalPhases - 1 && (
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

function getTotalPhases(visual: VisualExplanationType): number {
  switch (visual.scene_type) {
    case 'addition':
      return 4; // show group1, show group2, merge, show total
    case 'subtraction':
      return 4; // show all, highlight removal, remove, show remaining
    case 'fraction':
      return 3; // show bar, highlight parts, show label
    case 'multiplication':
      return 3; // show grid, fill, show total
    case 'counting':
      return (visual.result_count || 5) + 1; // one per object + final
    default:
      return 1;
  }
}

function getDelay(visual: VisualExplanationType, _phase: number): number {
  if (visual.scene_type === 'counting') return 900;
  return 1200;
}

function renderScene(visual: VisualExplanationType, phase: number): React.ReactNode {
  switch (visual.scene_type) {
    case 'addition':
      return renderAddition(visual, phase);
    case 'subtraction':
      return renderSubtraction(visual, phase);
    case 'fraction':
      return renderFraction(visual, phase);
    case 'multiplication':
      return renderMultiplication(visual, phase);
    case 'counting':
      return renderCounting(visual, phase);
    default:
      return <div style={{ padding: '20px', textAlign: 'center', color: '#94a3b8' }}>Visual: {visual.scene_type}</div>;
  }
}

// ─── Addition ───────────────────────────────────────

function renderAddition(visual: VisualExplanationType, phase: number) {
  const g1 = visual.group1_count || 0;
  const g2 = visual.group2_count || 0;
  const total = visual.result_count || g1 + g2;
  const emoji = visual.object_emoji || DEFAULT_EMOJI;

  const showGroup1 = phase >= 0;
  const showGroup2 = phase >= 1;
  const merged = phase >= 2;
  const showTotal = phase >= 3;

  const preMaxPerRow = 5;
  const mergedMaxPerRow = 8;

  // Calculate dynamic heights
  const preRows = Math.max(Math.ceil(g1 / preMaxPerRow), Math.ceil(g2 / preMaxPerRow));
  const preHeight = 30 + preRows * 36 + 20;
  const mergedRows = Math.ceil(total / mergedMaxPerRow);
  const mergedGridBottom = 30 + mergedRows * 36;
  const mergedHeight = mergedGridBottom + (showTotal ? 40 : 10);
  const viewHeight = merged ? mergedHeight : Math.max(preHeight, 90);

  return (
    <svg viewBox={`0 0 320 ${viewHeight}`} className="visual-svg">
      {/* Group 1 */}
      {showGroup1 && !merged && (() => {
        const g1Cols = Math.min(g1, preMaxPerRow);
        const g1Width = g1Cols * 28;
        const g1StartX = 80 - g1Width / 2;
        return (
          <g>
            <text x="80" y="20" textAnchor="middle" className="visual-group-label" fill={COLORS.group1}>{g1}</text>
            {renderObjectGrid(emoji, g1, g1StartX, 30, preMaxPerRow, COLORS.group1, 'g1')}
          </g>
        );
      })()}

      {/* Plus sign */}
      {showGroup2 && !merged && (
        <text x="160" y="75" textAnchor="middle" className="visual-operator" fill={COLORS.text}>+</text>
      )}

      {/* Group 2 */}
      {showGroup2 && !merged && (() => {
        const g2Cols = Math.min(g2, preMaxPerRow);
        const g2Width = g2Cols * 28;
        const g2StartX = 240 - g2Width / 2;
        return (
          <g>
            <text x="240" y="20" textAnchor="middle" className="visual-group-label" fill={COLORS.group2}>{g2}</text>
            {renderObjectGrid(emoji, g2, g2StartX, 30, preMaxPerRow, COLORS.group2, 'g2')}
          </g>
        );
      })()}

      {/* Merged result */}
      {merged && (
        <g className="visual-fade-in">
          {renderObjectGridCentered(emoji, total, 320, 30, mergedMaxPerRow, COLORS.result, 'merged')}
          {showTotal && (
            <text x="160" y={mergedGridBottom + 25} textAnchor="middle" className="visual-result-label" fill={COLORS.result}>
              = {total}
            </text>
          )}
        </g>
      )}
    </svg>
  );
}

// ─── Subtraction ────────────────────────────────────

function renderSubtraction(visual: VisualExplanationType, phase: number) {
  const start = visual.group1_count || 0;
  const remove = visual.group2_count || 0;
  const remaining = visual.result_count || (start - remove);
  const emoji = visual.object_emoji || DEFAULT_EMOJI;

  const maxPerRow = 8;
  const showAll = phase >= 0;
  const highlightRemoval = phase >= 1;
  const removed = phase >= 2;
  const showResult = phase >= 3;

  const count = removed ? remaining : start;
  const gridRows = Math.ceil(start / maxPerRow);
  const gridBottom = 30 + gridRows * 40;
  const viewHeight = gridBottom + (showResult ? 40 : 10);

  return (
    <svg viewBox={`0 0 320 ${viewHeight}`} className="visual-svg">
      {showAll && (
        <g>
          {Array.from({ length: count }).map((_, i) => {
            const col = i % maxPerRow;
            const row = Math.floor(i / maxPerRow);
            const cols = Math.min(count, maxPerRow);
            const gridWidth = cols * 36;
            const offsetX = (320 - gridWidth) / 2;
            const x = offsetX + col * 36;
            const y = 30 + row * 40;
            return (
              <text
                key={`obj-${i}`}
                x={x + 14}
                y={y + 28}
                textAnchor="middle"
                fontSize="24"
                className="visual-fade-in"
              >
                {emoji}
              </text>
            );
          })}
          {/* Show crossed-out items during highlight phase */}
          {highlightRemoval && !removed && Array.from({ length: remove }).map((_, i) => {
            const idx = start - 1 - i;
            const col = idx % maxPerRow;
            const row = Math.floor(idx / maxPerRow);
            const crossCols = Math.min(count, maxPerRow);
            const crossGridWidth = crossCols * 36;
            const crossOffsetX = (320 - crossGridWidth) / 2;
            const x = crossOffsetX + col * 36;
            const y = 30 + row * 40;
            return (
              <g key={`cross-${i}`} className="visual-fade-in">
                <line x1={x} y1={y + 5} x2={x + 28} y2={y + 30} stroke="#EF4444" strokeWidth="3" />
                <line x1={x + 28} y1={y + 5} x2={x} y2={y + 30} stroke="#EF4444" strokeWidth="3" />
              </g>
            );
          })}
        </g>
      )}
      {showResult && (
        <text x="160" y={gridBottom + 25} textAnchor="middle" className="visual-result-label" fill={COLORS.result}>
          {start} - {remove} = {remaining}
        </text>
      )}
    </svg>
  );
}

// ─── Fraction ───────────────────────────────────────

function renderFraction(visual: VisualExplanationType, phase: number) {
  const total = visual.total_parts || 4;
  const highlighted = visual.highlighted_parts || 1;
  const label = visual.fraction_label || `${highlighted}/${total}`;

  const showBar = phase >= 0;
  const showHighlight = phase >= 1;
  const showLabel = phase >= 2;

  const barWidth = 260;
  const barHeight = 50;
  const barX = 30;
  const barY = 60;
  const partWidth = barWidth / total;

  return (
    <svg viewBox="0 0 320 180" className="visual-svg">
      {showBar && (
        <g>
          {/* Bar segments */}
          {Array.from({ length: total }).map((_, i) => (
            <rect
              key={`part-${i}`}
              x={barX + i * partWidth}
              y={barY}
              width={partWidth}
              height={barHeight}
              fill={showHighlight && i < highlighted ? COLORS.barFill : COLORS.bar}
              stroke="#94A3B8"
              strokeWidth="2"
              rx="2"
              className={showHighlight && i < highlighted ? 'visual-fade-in' : ''}
            />
          ))}

          {/* Part labels */}
          {Array.from({ length: total }).map((_, i) => (
            <text
              key={`label-${i}`}
              x={barX + i * partWidth + partWidth / 2}
              y={barY + barHeight + 20}
              textAnchor="middle"
              fontSize="12"
              fill={showHighlight && i < highlighted ? COLORS.barFill : '#94A3B8'}
            >
              {i + 1}
            </text>
          ))}
        </g>
      )}

      {showLabel && (
        <text
          x="160"
          y="160"
          textAnchor="middle"
          className="visual-result-label visual-fade-in"
          fill={COLORS.highlight}
        >
          {label}
        </text>
      )}

      {/* Title above bar */}
      {showBar && (
        <text x="160" y="40" textAnchor="middle" fontSize="14" fill={COLORS.text}>
          {showHighlight
            ? `${highlighted} out of ${total} parts`
            : `${total} equal parts`}
        </text>
      )}
    </svg>
  );
}

// ─── Multiplication ─────────────────────────────────

function renderMultiplication(visual: VisualExplanationType, phase: number) {
  const rows = visual.rows || 3;
  const cols = visual.cols || 4;
  const total = visual.result_count || rows * cols;
  const emoji = visual.object_emoji || DEFAULT_EMOJI;

  const showGrid = phase >= 0;
  const filled = phase >= 1;
  const showTotal = phase >= 2;

  const cellSize = Math.min(36, 280 / Math.max(cols, 1));
  const gridWidth = cols * cellSize;
  const gridHeight = rows * cellSize;
  const startX = (320 - gridWidth) / 2;
  const startY = 30;

  return (
    <svg viewBox="0 0 320 200" className="visual-svg">
      {showGrid && (
        <g>
          {/* Row label */}
          <text x={startX - 10} y={startY + gridHeight / 2 + 5} textAnchor="end" fontSize="14" fill={COLORS.group1}>
            {rows} rows
          </text>

          {/* Column label */}
          <text x={startX + gridWidth / 2} y={startY - 8} textAnchor="middle" fontSize="14" fill={COLORS.group2}>
            {cols} columns
          </text>

          {/* Grid cells */}
          {Array.from({ length: rows }).map((_, r) =>
            Array.from({ length: cols }).map((_, c) => {
              const x = startX + c * cellSize;
              const y = startY + r * cellSize;
              return (
                <g key={`cell-${r}-${c}`}>
                  <rect
                    x={x}
                    y={y}
                    width={cellSize}
                    height={cellSize}
                    fill={filled ? '#EFF6FF' : 'white'}
                    stroke="#CBD5E1"
                    strokeWidth="1"
                  />
                  {filled && (
                    <text
                      x={x + cellSize / 2}
                      y={y + cellSize / 2 + 7}
                      textAnchor="middle"
                      fontSize={Math.min(20, cellSize - 6)}
                      className="visual-fade-in"
                    >
                      {emoji}
                    </text>
                  )}
                </g>
              );
            })
          )}
        </g>
      )}

      {showTotal && (
        <text
          x="160"
          y={startY + gridHeight + 30}
          textAnchor="middle"
          className="visual-result-label visual-fade-in"
          fill={COLORS.result}
        >
          {rows} × {cols} = {total}
        </text>
      )}
    </svg>
  );
}

// ─── Counting ───────────────────────────────────────

function renderCounting(visual: VisualExplanationType, phase: number) {
  const total = visual.result_count || 5;
  const emoji = visual.object_emoji || DEFAULT_EMOJI;
  const visibleCount = Math.min(phase, total);
  const showFinal = phase >= total;

  const maxPerRow = 5;
  const gridRows = Math.ceil(total / maxPerRow);
  const gridBottom = 20 + gridRows * 50;
  const viewHeight = gridBottom + (showFinal ? 35 : 5);

  return (
    <svg viewBox={`0 0 320 ${viewHeight}`} className="visual-svg">
      {Array.from({ length: visibleCount }).map((_, i) => {
        const col = i % maxPerRow;
        const row = Math.floor(i / maxPerRow);
        const cols = Math.min(total, maxPerRow);
        const gridWidth = cols * 50;
        const offsetX = (320 - gridWidth) / 2;
        const x = offsetX + col * 50;
        const y = 20 + row * 50;
        return (
          <g key={`count-${i}`} className="visual-pop-in">
            <text x={x + 18} y={y + 32} textAnchor="middle" fontSize="28">{emoji}</text>
            <text x={x + 18} y={y + 48} textAnchor="middle" fontSize="10" fill={COLORS.text}>{i + 1}</text>
          </g>
        );
      })}

      {showFinal && (
        <text
          x="160"
          y={gridBottom + 20}
          textAnchor="middle"
          className="visual-result-label visual-fade-in"
          fill={COLORS.result}
        >
          Total: {total}
        </text>
      )}
    </svg>
  );
}

// ─── Helpers ────────────────────────────────────────

function renderObjectGridCentered(
  emoji: string,
  count: number,
  viewBoxWidth: number,
  startY: number,
  maxPerRow: number,
  color: string,
  keyPrefix: string,
) {
  const cols = Math.min(count, maxPerRow);
  const gridWidth = cols * 28;
  const startX = (viewBoxWidth - gridWidth) / 2;
  return renderObjectGrid(emoji, count, startX, startY, maxPerRow, color, keyPrefix);
}

function renderObjectGrid(
  emoji: string,
  count: number,
  startX: number,
  startY: number,
  maxPerRow: number,
  _color: string,
  keyPrefix: string,
) {
  return Array.from({ length: count }).map((_, i) => {
    const col = i % maxPerRow;
    const row = Math.floor(i / maxPerRow);
    const x = startX + col * 28;
    const y = startY + row * 36;
    return (
      <text
        key={`${keyPrefix}-${i}`}
        x={x + 14}
        y={y + 28}
        textAnchor="middle"
        fontSize="22"
        className="visual-pop-in"
      >
        {emoji}
      </text>
    );
  });
}
