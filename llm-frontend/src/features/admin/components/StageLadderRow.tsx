/**
 * StageLadderRow — one row in the Topic Pipeline Dashboard ladder.
 *
 * Renders the status badge, stage summary, warnings, and deep links to the
 * existing per-stage admin page. In Phase 2+ the row also surfaces
 * Regenerate/Run/Retry action buttons wired to the stage-level endpoints.
 */
import React from 'react';
import type { StageStatus, StageId, StageState } from '../api/adminApiV2';

interface StageLabel {
  number: string;
  title: string;
  adminPath: (bookId: string, chapterId: string) => string;
}

const STAGE_LABELS: Record<StageId, StageLabel> = {
  explanations: {
    number: '①',
    title: 'Explanations',
    adminPath: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  },
  visuals: {
    number: '②',
    title: 'Visuals',
    adminPath: (b, c) => `/admin/books-v2/${b}/visuals/${c}`,
  },
  check_ins: {
    number: '③',
    title: 'Check-ins',
    adminPath: (b, c) => `/admin/books-v2/${b}/check-ins/${c}`,
  },
  practice_bank: {
    number: '④',
    title: 'Practice bank',
    adminPath: (b, c) => `/admin/books-v2/${b}/practice-banks/${c}`,
  },
  audio_review: {
    number: '⑤',
    title: 'Audio review',
    adminPath: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  },
  audio_synthesis: {
    number: '⑥',
    title: 'Audio synthesis',
    adminPath: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  },
};

const STATE_STYLE: Record<
  StageState,
  { icon: string; bg: string; fg: string; label: string }
> = {
  done: { icon: '✓', bg: '#D1FAE5', fg: '#065F46', label: 'Done' },
  warning: { icon: '⚠', bg: '#FEF3C7', fg: '#92400E', label: 'Warning' },
  running: { icon: '◐', bg: '#DBEAFE', fg: '#1D4ED8', label: 'Running' },
  ready: { icon: '○', bg: '#F3F4F6', fg: '#4B5563', label: 'Ready' },
  blocked: { icon: '▣', bg: '#FEE2E2', fg: '#991B1B', label: 'Blocked' },
  failed: { icon: '✕', bg: '#FEE2E2', fg: '#991B1B', label: 'Failed' },
};

interface StageLadderRowProps {
  stage: StageStatus;
  bookId: string;
  chapterId: string;
  onRetry?: (stageId: StageId) => void;
  onRegenerate?: (stageId: StageId) => void;
  onRun?: (stageId: StageId) => void;
  onRunSkipReview?: () => void;
  disableActions?: boolean;
}

const StageLadderRow: React.FC<StageLadderRowProps> = ({
  stage,
  bookId,
  chapterId,
  onRetry,
  onRegenerate,
  onRun,
  onRunSkipReview,
  disableActions,
}) => {
  const meta = STAGE_LABELS[stage.stage_id];
  const style = STATE_STYLE[stage.state];
  const adminPath = meta.adminPath(bookId, chapterId);

  const showRegenerate =
    (stage.state === 'done' || stage.state === 'warning') && onRegenerate;
  const showRun =
    (stage.state === 'ready' || stage.state === 'blocked') && onRun;
  const showRetry = stage.state === 'failed' && onRetry;
  const showRunSkipReview =
    stage.state === 'blocked' &&
    stage.stage_id === 'audio_synthesis' &&
    onRunSkipReview;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '16px',
        padding: '16px 20px',
        borderBottom: '1px solid #E5E7EB',
        backgroundColor: stage.state === 'running' ? '#F5F9FF' : 'white',
      }}
    >
      <div
        style={{
          flex: '0 0 48px',
          fontSize: '22px',
          fontWeight: 700,
          color: '#6B7280',
          marginTop: 2,
        }}
      >
        {meta.number}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: 4,
          }}
        >
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#111827' }}>
            {meta.title}
          </span>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '2px 8px',
              borderRadius: '10px',
              backgroundColor: style.bg,
              color: style.fg,
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            <span>{style.icon}</span>
            <span>{style.label}</span>
          </span>
          {stage.is_stale && (
            <span
              style={{
                padding: '2px 8px',
                borderRadius: '10px',
                backgroundColor: '#FEF3C7',
                color: '#92400E',
                fontSize: '11px',
                fontWeight: 600,
              }}
            >
              Stale
            </span>
          )}
        </div>

        <div style={{ fontSize: '13px', color: '#4B5563' }}>{stage.summary}</div>

        {stage.warnings && stage.warnings.length > 0 && (
          <ul
            style={{
              margin: '6px 0 0 0',
              padding: '0 0 0 16px',
              fontSize: '12px',
              color: '#92400E',
            }}
          >
            {stage.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}

        {stage.last_job_error && stage.state === 'failed' && (
          <div
            style={{
              marginTop: 6,
              padding: '6px 10px',
              backgroundColor: '#FEF2F2',
              border: '1px solid #FCA5A5',
              borderRadius: 4,
              fontSize: '12px',
              color: '#991B1B',
              fontFamily: 'monospace',
              whiteSpace: 'pre-wrap',
            }}
          >
            {stage.last_job_error}
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', marginTop: 10 }}>
          <a
            href={adminPath}
            style={{
              padding: '6px 12px',
              fontSize: '13px',
              color: '#4F46E5',
              textDecoration: 'none',
              borderRadius: 4,
              border: '1px solid #C7D2FE',
              backgroundColor: 'white',
            }}
          >
            Open stage page →
          </a>

          {showRegenerate && (
            <button
              type="button"
              disabled={disableActions}
              onClick={() => onRegenerate?.(stage.stage_id)}
              style={{
                padding: '6px 12px',
                fontSize: '13px',
                color: '#374151',
                backgroundColor: '#F3F4F6',
                border: '1px solid #D1D5DB',
                borderRadius: 4,
                cursor: disableActions ? 'not-allowed' : 'pointer',
                opacity: disableActions ? 0.6 : 1,
              }}
            >
              Regenerate
            </button>
          )}

          {showRun && (
            <button
              type="button"
              disabled={disableActions}
              onClick={() => onRun?.(stage.stage_id)}
              style={{
                padding: '6px 12px',
                fontSize: '13px',
                color: 'white',
                backgroundColor: '#4F46E5',
                border: 'none',
                borderRadius: 4,
                cursor: disableActions ? 'not-allowed' : 'pointer',
                opacity: disableActions ? 0.6 : 1,
              }}
            >
              Run
            </button>
          )}

          {showRunSkipReview && (
            <button
              type="button"
              disabled={disableActions}
              onClick={onRunSkipReview}
              style={{
                padding: '6px 12px',
                fontSize: '13px',
                color: '#92400E',
                backgroundColor: '#FEF3C7',
                border: '1px solid #FDE68A',
                borderRadius: 4,
                cursor: disableActions ? 'not-allowed' : 'pointer',
              }}
            >
              Run anyway — skip review
            </button>
          )}

          {showRetry && (
            <button
              type="button"
              disabled={disableActions}
              onClick={() => onRetry?.(stage.stage_id)}
              style={{
                padding: '6px 12px',
                fontSize: '13px',
                color: 'white',
                backgroundColor: '#DC2626',
                border: 'none',
                borderRadius: 4,
                cursor: disableActions ? 'not-allowed' : 'pointer',
                opacity: disableActions ? 0.6 : 1,
              }}
            >
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default StageLadderRow;
