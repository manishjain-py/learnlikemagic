/**
 * TopicDAGView — React Flow-based per-topic DAG dashboard.
 *
 * Replaces the stage-ladder TopicPipelineDashboard. Renders the 8-stage topic
 * pipeline as a directed graph with auto-layout (BFS depth → row groups) and
 * polls per-stage state durably from `topic_stage_runs`. Click a node for a
 * side panel with rerun + deep-link.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  ApiError,
  cancelCascade,
  getCrossDagWarnings,
  getDAGDefinition,
  getTopicDAG,
  getTopicPipeline,
  rerunStageCascade,
  runAllStagesCascade,
  type CascadeInfo,
  type CrossDagWarning,
  type DAGDefinitionResponse,
  type TopicDAGResponse,
  type TopicDAGStageRow,
  type TopicStageRunState,
} from '../api/adminApiV2';

// ───────── Layout constants (BFS depth → grid) ─────────
const NODE_WIDTH = 260;
const NODE_HEIGHT = 110;
// Wide horizontal gap so adjacent siblings don't kiss; wide vertical gap so
// edges from a many-children parent (e.g. Explanations → 5 children) have
// room to fan out without sharing a single horizontal trunk at the midpoint.
const NODE_H_GAP = 110;
const NODE_V_GAP = 200;

interface LayoutPos {
  x: number;
  y: number;
}

interface DAGNode {
  id: string;
  label: string;
  depends_on: string[];
}

/**
 * Two-pass hierarchical layout — BFS-depth rows + parent-aligned columns.
 *
 * The naive "center each row against the widest row" approach (the original
 * port from the reference orchestrator) packs leaves into the middle of the
 * canvas regardless of which parent they hang off, which produces long
 * crossing edges as soon as there are more than two leaves on a wide row.
 *
 * Instead:
 *   1. BFS-assign each node a depth (row).
 *   2. Top-down sweep: place each node at avg(parent.x), then push siblings
 *      apart to enforce min spacing.
 *   3. Bottom-up sweep: pull each parent toward avg(child.x) so multi-child
 *      nodes sit centered above their subtree.
 *   4. Normalize so the canvas starts at x=0.
 *
 * Pure tree shapes converge in one pass each; DAGs with shared descendants
 * will look reasonable too because the spacing pass never lets nodes
 * overlap.
 */
function computeLayout(
  stages: DAGNode[],
): Record<string, LayoutPos> {
  if (stages.length === 0) return {};

  const inDeg: Record<string, number> = {};
  const children: Record<string, string[]> = {};
  const parents: Record<string, string[]> = {};
  stages.forEach((s) => {
    inDeg[s.id] = 0;
    children[s.id] = [];
    parents[s.id] = [];
  });
  stages.forEach((s) => {
    s.depends_on.forEach((dep) => {
      if (children[dep]) {
        children[dep].push(s.id);
        parents[s.id].push(dep);
        inDeg[s.id] = (inDeg[s.id] || 0) + 1;
      }
    });
  });

  // BFS depth assignment — each node placed at max(parent_depth) + 1.
  const level: Record<string, number> = {};
  const inDegMut = { ...inDeg };
  const queue: string[] = stages.filter((s) => (inDegMut[s.id] || 0) === 0).map((s) => s.id);
  queue.forEach((id) => {
    level[id] = 0;
  });
  const visited = new Set<string>();
  while (queue.length > 0) {
    const id = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    (children[id] || []).forEach((childId) => {
      level[childId] = Math.max(level[childId] || 0, (level[id] ?? 0) + 1);
      inDegMut[childId] = (inDegMut[childId] || 1) - 1;
      if (inDegMut[childId] <= 0) queue.push(childId);
    });
  }

  // Group nodes by row, preserving STAGES order within each row so cosmetic
  // ordering is deterministic + matches the dependency declaration order.
  const rows: Record<number, string[]> = {};
  stages.forEach((s) => {
    const l = level[s.id] ?? 0;
    if (!rows[l]) rows[l] = [];
    rows[l].push(s.id);
  });

  const xStep = NODE_WIDTH + NODE_H_GAP;
  const x: Record<string, number> = {};
  const sortedLevels = Object.keys(rows)
    .map(Number)
    .sort((a, b) => a - b);

  // Pass 1 (top-down): each node wants to sit at avg(parent.x); enforce
  // min spacing within its row by left-to-right sweep on the desired x.
  for (const l of sortedLevels) {
    const ids = rows[l];
    const desired = ids.map((id) => {
      const ps = parents[id];
      const ideal =
        ps.length > 0
          ? ps.reduce((sum, p) => sum + (x[p] ?? 0), 0) / ps.length
          : 0;
      return { id, ideal };
    });
    desired.sort((a, b) => a.ideal - b.ideal);
    let lastX = -Infinity;
    desired.forEach(({ id, ideal }) => {
      const placed = Math.max(ideal, lastX === -Infinity ? ideal : lastX + xStep);
      x[id] = placed;
      lastX = placed;
    });
  }

  // Pass 2 (bottom-up): pull each parent toward avg(child.x) so the parent
  // ends up centered above its subtree, then re-enforce min spacing.
  for (const l of [...sortedLevels].reverse()) {
    const ids = rows[l];
    const desired = ids.map((id) => {
      const cs = children[id];
      if (cs.length === 0) return { id, ideal: x[id] };
      const childAvg = cs.reduce((sum, c) => sum + (x[c] ?? 0), 0) / cs.length;
      return { id, ideal: Math.max(x[id], childAvg) };
    });
    desired.sort((a, b) => a.ideal - b.ideal);
    let lastX = -Infinity;
    desired.forEach(({ id, ideal }) => {
      const placed = Math.max(ideal, lastX === -Infinity ? ideal : lastX + xStep);
      x[id] = placed;
      lastX = placed;
    });
  }

  // Normalize: shift everything so min x is 0.
  const minX = Math.min(...Object.values(x));
  const pos: Record<string, LayoutPos> = {};
  stages.forEach((s) => {
    pos[s.id] = {
      x: (x[s.id] ?? 0) - minX,
      y: (level[s.id] ?? 0) * NODE_V_GAP,
    };
  });
  return pos;
}

// ───────── Node visuals ─────────

const STATE_STYLE: Record<
  TopicStageRunState,
  { border: string; bg: string; fg: string; label: string; animate: boolean }
> = {
  pending: { border: '#D1D5DB', bg: '#F9FAFB', fg: '#6B7280', label: 'Pending', animate: false },
  running: { border: '#3B82F6', bg: '#EFF6FF', fg: '#1D4ED8', label: 'Running', animate: true },
  done: { border: '#10B981', bg: '#ECFDF5', fg: '#065F46', label: 'Done', animate: false },
  failed: { border: '#EF4444', bg: '#FEF2F2', fg: '#991B1B', label: 'Failed', animate: false },
};

interface StageNodeData extends Record<string, unknown> {
  row: TopicDAGStageRow;
  selected: boolean;
  isCascadeRunning: boolean;
  onClick: (stageId: string) => void;
}

function StageNode({ data }: NodeProps<Node<StageNodeData>>) {
  const { row, selected, isCascadeRunning, onClick } = data;
  const style = STATE_STYLE[row.state];
  const isRunningHere = row.state === 'running' || isCascadeRunning;
  const showStaleBadge = row.is_stale && row.state === 'done';

  return (
    <div
      onClick={() => onClick(row.stage_id)}
      style={{
        position: 'relative',
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        padding: '12px 14px',
        borderRadius: 10,
        border: `2px solid ${selected ? '#4F46E5' : style.border}`,
        backgroundColor: style.bg,
        boxShadow: selected
          ? '0 0 0 3px rgba(79, 70, 229, 0.15)'
          : '0 1px 2px rgba(0,0,0,0.05)',
        cursor: 'pointer',
        transition: 'box-shadow 0.15s, border-color 0.15s',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: '#9CA3AF', width: 6, height: 6, border: 'none' }}
      />

      {/* Stale corner badge */}
      {showStaleBadge && (
        <span
          title="Marked stale by an upstream rerun"
          style={{
            position: 'absolute',
            top: 6,
            right: 6,
            padding: '1px 6px',
            fontSize: 10,
            fontWeight: 700,
            color: '#92400E',
            backgroundColor: '#FEF3C7',
            border: '1px solid #FBBF24',
            borderRadius: 999,
          }}
        >
          STALE
        </span>
      )}

      {/* Title */}
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: '#111827',
          marginBottom: 6,
          paddingRight: showStaleBadge ? 56 : 0,
          lineHeight: 1.25,
        }}
      >
        {row.label}
      </div>

      {/* State badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            fontSize: 11,
            fontWeight: 600,
            color: style.fg,
            backgroundColor: 'white',
            border: `1px solid ${style.border}`,
            borderRadius: 999,
          }}
        >
          {isRunningHere && (
            <span
              style={{
                display: 'inline-block',
                width: 6,
                height: 6,
                borderRadius: '50%',
                backgroundColor: '#3B82F6',
                animation: 'pulse 1.4s ease-in-out infinite',
              }}
            />
          )}
          {style.label}
        </span>
      </div>

      {/* Duration / last-run timestamp */}
      <div style={{ fontSize: 11, color: '#6B7280', lineHeight: 1.3 }}>
        {formatNodeFooter(row)}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: '#9CA3AF', width: 6, height: 6, border: 'none' }}
      />
    </div>
  );
}

function formatNodeFooter(row: TopicDAGStageRow): string {
  const parts: string[] = [];
  if (row.duration_ms != null) {
    parts.push(formatDuration(row.duration_ms));
  }
  const ts = row.completed_at || row.started_at;
  if (ts) {
    parts.push(formatRelativeTime(ts));
  }
  if (parts.length === 0) return 'Not yet run';
  return parts.join(' · ');
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s - m * 60);
  return `${m}m ${rs}s`;
}

// Backend `topic_stage_runs` writes naive UTC datetimes via `datetime.utcnow()`.
// FastAPI serializes them without an offset (e.g. "2026-04-29T01:23:17.499756").
// `new Date(...)` on such a string parses as LOCAL time, so we coerce to UTC.
function parseBackendDatetime(iso: string): Date {
  const hasOffset = /([Zz]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasOffset ? iso : `${iso}Z`);
}

function formatRelativeTime(iso: string): string {
  const ts = parseBackendDatetime(iso).getTime();
  if (Number.isNaN(ts)) return '';
  const diff = Date.now() - ts;
  if (diff < 0) return 'just now';
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

const NODE_TYPES = { stage: StageNode };

// ───────── Polling cadence ─────────
const POLL_FAST_MS = 2000; // any stage running OR active cascade
const POLL_SLOW_MS = 30000;

function isAnyActive(dag: TopicDAGResponse | null): boolean {
  if (!dag) return false;
  if (dag.cascade && (dag.cascade.running || dag.cascade.pending.length > 0)) return true;
  return dag.stages.some((s) => s.state === 'running');
}

// ───────── Page component ─────────

interface ToastState {
  kind: 'error' | 'warn' | 'success';
  message: string;
}

const TopicDAGView: React.FC = () => {
  const { bookId, chapterId, topicKey } = useParams<{
    bookId: string;
    chapterId: string;
    topicKey: string;
  }>();
  const navigate = useNavigate();

  const [guidelineId, setGuidelineId] = useState<string | null>(null);
  const [topicTitle, setTopicTitle] = useState<string>('');
  const [definition, setDefinition] = useState<DAGDefinitionResponse | null>(null);
  const [dag, setDag] = useState<TopicDAGResponse | null>(null);
  const [warnings, setWarnings] = useState<CrossDagWarning[]>([]);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);

  const pollTimerRef = useRef<number | null>(null);
  const aliveRef = useRef(true);

  // Step 1 — resolve guideline_id from (book, chapter, topic_key).
  // Resetting topic-scoped state on every param change is critical for
  // correctness: actions (rerun/run-all/cancel) read `guidelineId` from
  // closure, and an unreset id would target the previous topic.
  useEffect(() => {
    aliveRef.current = true;
    setGuidelineId(null);
    setDag(null);
    setWarnings([]);
    setTopicTitle('');
    setSelectedStageId(null);
    setResolveError(null);
    setToast(null);
    if (!bookId || !chapterId || !topicKey) return;

    let cancelled = false;
    (async () => {
      try {
        const status = await getTopicPipeline(bookId, chapterId, topicKey);
        if (cancelled) return;
        setGuidelineId(status.guideline_id);
        setTopicTitle(status.topic_title || topicKey);
      } catch (err) {
        if (cancelled) return;
        setResolveError(
          err instanceof Error ? err.message : 'Failed to resolve topic',
        );
      }
    })();
    return () => {
      cancelled = true;
      aliveRef.current = false;
    };
  }, [bookId, chapterId, topicKey]);

  // Step 2 — fetch DAG topology once.
  useEffect(() => {
    let cancelled = false;
    getDAGDefinition()
      .then((def) => {
        if (!cancelled) setDefinition(def);
      })
      .catch((err) => {
        if (!cancelled) {
          setToast({
            kind: 'error',
            message:
              err instanceof Error ? err.message : 'Failed to load DAG definition',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Step 3 — poll DAG state.
  const fetchDAG = useCallback(async (): Promise<TopicDAGResponse | null> => {
    if (!guidelineId) return null;
    try {
      const resp = await getTopicDAG(guidelineId);
      if (!aliveRef.current) return null;
      setDag(resp);
      return resp;
    } catch (err) {
      if (!aliveRef.current) return null;
      setToast({
        kind: 'error',
        message: err instanceof Error ? err.message : 'Failed to load DAG state',
      });
      return null;
    }
  }, [guidelineId]);

  // Cross-DAG warnings poll alongside DAG state but stay silent on failure —
  // they're a soft signal and a transient endpoint blip shouldn't spam toasts
  // every 2s. The banner just won't update; the next successful tick recovers.
  const fetchWarnings = useCallback(async (): Promise<void> => {
    if (!guidelineId) return;
    try {
      const resp = await getCrossDagWarnings(guidelineId);
      if (!aliveRef.current) return;
      setWarnings(resp.warnings);
    } catch {
      // Silent — don't clear existing warnings either; stale-but-known beats
      // disappearing the banner on a single network hiccup.
    }
  }, [guidelineId]);

  const clearTimer = useCallback(() => {
    if (pollTimerRef.current != null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const tick = useCallback(async () => {
    if (!aliveRef.current) return;
    if (document.hidden) return; // resumed by visibilitychange handler below
    const [next] = await Promise.all([fetchDAG(), fetchWarnings()]);
    if (!aliveRef.current) return;
    if (document.hidden) return;
    const interval = isAnyActive(next) ? POLL_FAST_MS : POLL_SLOW_MS;
    pollTimerRef.current = window.setTimeout(tick, interval);
  }, [fetchDAG, fetchWarnings]);

  useEffect(() => {
    if (!guidelineId) return;
    aliveRef.current = true;
    tick();

    const onVisibility = () => {
      if (!aliveRef.current) return;
      if (document.hidden) {
        clearTimer();
      } else {
        clearTimer();
        tick();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      aliveRef.current = false;
      clearTimer();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [guidelineId, tick, clearTimer]);

  // ───────── Layout & React Flow data ─────────

  const stagesForLayout: DAGNode[] = useMemo(() => {
    if (!definition) return [];
    return definition.stages.map((s) => ({
      id: s.id,
      label: s.label,
      depends_on: s.depends_on,
    }));
  }, [definition]);

  const layout = useMemo(() => computeLayout(stagesForLayout), [stagesForLayout]);

  const stageRowById: Record<string, TopicDAGStageRow> = useMemo(() => {
    const map: Record<string, TopicDAGStageRow> = {};
    if (!dag) return map;
    dag.stages.forEach((s) => {
      map[s.stage_id] = s;
    });
    return map;
  }, [dag]);

  const cascadeRunningStage = dag?.cascade?.running ?? null;

  const handleNodeClick = useCallback((stageId: string) => {
    setSelectedStageId(stageId);
  }, []);

  const nodes: Node<StageNodeData>[] = useMemo(() => {
    if (!definition) return [];
    return definition.stages.map((s) => {
      const row: TopicDAGStageRow =
        stageRowById[s.id] ?? {
          stage_id: s.id,
          label: s.label,
          depends_on: s.depends_on,
          state: 'pending',
        };
      return {
        id: s.id,
        type: 'stage',
        position: layout[s.id] ?? { x: 0, y: 0 },
        data: {
          row,
          selected: selectedStageId === s.id,
          isCascadeRunning: cascadeRunningStage === s.id,
          onClick: handleNodeClick,
        },
      };
    });
  }, [definition, layout, stageRowById, selectedStageId, cascadeRunningStage, handleNodeClick]);

  const edges: Edge[] = useMemo(() => {
    if (!definition) return [];
    const out: Edge[] = [];
    definition.stages.forEach((s) => {
      s.depends_on.forEach((dep) => {
        const animate =
          stageRowById[s.id]?.state === 'running' ||
          stageRowById[dep]?.state === 'running';
        out.push({
          id: `${dep}->${s.id}`,
          source: dep,
          target: s.id,
          // Bezier (React Flow's `default`) so each edge draws its own smooth
          // curve from source to target. `smoothstep` shared a horizontal
          // trunk at the midpoint y for many-children parents (Explanations →
          // 5 fan-outs), which read as overlapping/bunched.
          type: 'default',
          animated: animate,
          style: { stroke: '#9CA3AF', strokeWidth: 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#9CA3AF' },
        });
      });
    });
    return out;
  }, [definition, stageRowById]);

  // ───────── Cascade actions ─────────

  const handleApiError = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail as { code?: string; message?: string };
        const code = detail?.code || 'conflict';
        const codeLabels: Record<string, string> = {
          cascade_active:
            'A cascade is already running for this topic. Wait for it to settle, or cancel it first.',
          upstream_not_done:
            'Upstream stage is not done. Run upstream first or use Run all.',
          stage_running:
            'Another job is already running for this topic. Wait for it to finish.',
        };
        setToast({
          kind: 'warn',
          message: codeLabels[code] || detail?.message || fallback,
        });
        return;
      }
      setToast({
        kind: 'error',
        message: err instanceof Error ? err.message : fallback,
      });
    },
    [],
  );

  const handleRerun = useCallback(
    async (stageId: string) => {
      if (!guidelineId) return;
      setActionInFlight(`rerun:${stageId}`);
      setToast(null);
      try {
        const resp = await rerunStageCascade(guidelineId, stageId, { force: true });
        setToast({
          kind: 'success',
          message: `Cascade started · running ${resp.running ?? stageId} · ${resp.pending.length} pending`,
        });
        clearTimer();
        await tick();
      } catch (err) {
        handleApiError(err, `Failed to rerun ${stageId}`);
      } finally {
        setActionInFlight(null);
      }
    },
    [guidelineId, clearTimer, tick, handleApiError],
  );

  const handleRunAll = useCallback(async () => {
    if (!guidelineId) return;
    setActionInFlight('run-all');
    setToast(null);
    try {
      const resp = await runAllStagesCascade(guidelineId, {});
      if (resp.message) {
        setToast({ kind: 'success', message: resp.message });
      } else {
        setToast({
          kind: 'success',
          message: `Cascade started · running ${resp.running ?? '—'} · ${resp.pending.length} pending`,
        });
      }
      clearTimer();
      await tick();
    } catch (err) {
      handleApiError(err, 'Failed to run all stages');
    } finally {
      setActionInFlight(null);
    }
  }, [guidelineId, clearTimer, tick, handleApiError]);

  const handleCancel = useCallback(async () => {
    if (!guidelineId) return;
    setActionInFlight('cancel');
    setToast(null);
    try {
      const resp = await cancelCascade(guidelineId);
      setToast({
        kind: resp.cancelled ? 'success' : 'warn',
        message: resp.cancelled
          ? 'Cascade cancellation requested. The current stage will finish; nothing else will launch.'
          : 'No active cascade to cancel.',
      });
      clearTimer();
      await tick();
    } catch (err) {
      handleApiError(err, 'Failed to cancel cascade');
    } finally {
      setActionInFlight(null);
    }
  }, [guidelineId, clearTimer, tick, handleApiError]);

  // ───────── Render ─────────

  if (!bookId || !chapterId || !topicKey) {
    return (
      <div style={{ padding: 24, color: '#991B1B' }}>
        Missing book/chapter/topic in URL.
      </div>
    );
  }

  const cascade: CascadeInfo | null = dag?.cascade ?? null;
  const cascadeActive = !!cascade && (!!cascade.running || cascade.pending.length > 0);
  const cascadeCancelling = !!cascade?.cancelled;
  // Server-side cascade.pending contains the running stage too; the user-facing
  // "remaining" count is everything pending minus whatever's currently running.
  const remainingStages = cascade
    ? cascade.pending.filter((s) => s !== cascade.running)
    : [];
  const selectedRow = selectedStageId ? stageRowById[selectedStageId] : null;
  const selectedDef = selectedStageId
    ? definition?.stages.find((s) => s.id === selectedStageId)
    : null;
  const stageRunning = selectedRow?.state === 'running';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)' }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.4); }
        }
      `}</style>

      {/* Top bar */}
      <div
        style={{
          padding: '12px 20px',
          borderBottom: '1px solid #E5E7EB',
          backgroundColor: 'white',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => navigate(`/admin/books-v2/${bookId}`)}
              style={{
                background: 'none',
                border: 'none',
                color: '#4F46E5',
                cursor: 'pointer',
                padding: 0,
                fontSize: 13,
              }}
            >
              ← Back to book
            </button>
            <span style={{ color: '#9CA3AF' }}>/</span>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{topicTitle || topicKey}</div>
              <div style={{ fontSize: 11, color: '#6B7280' }}>
                topic_key: <code>{topicKey}</code>
                {guidelineId && (
                  <>
                    {' · '}guideline_id: <code>{guidelineId.slice(0, 8)}…</code>
                  </>
                )}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              onClick={() => fetchDAG()}
              disabled={!guidelineId}
              style={{
                padding: '6px 12px',
                fontSize: 13,
                color: '#374151',
                backgroundColor: '#F3F4F6',
                border: '1px solid #D1D5DB',
                borderRadius: 4,
                cursor: guidelineId ? 'pointer' : 'not-allowed',
              }}
            >
              Refresh
            </button>
            {cascadeActive ? (
              <button
                type="button"
                onClick={handleCancel}
                disabled={actionInFlight === 'cancel' || cascadeCancelling}
                title={
                  cascadeCancelling
                    ? 'Cancellation requested — the running stage is finishing'
                    : undefined
                }
                style={{
                  padding: '6px 14px',
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'white',
                  backgroundColor:
                    actionInFlight === 'cancel' || cascadeCancelling ? '#9CA3AF' : '#DC2626',
                  border: 'none',
                  borderRadius: 4,
                  cursor:
                    actionInFlight === 'cancel' || cascadeCancelling
                      ? 'not-allowed'
                      : 'pointer',
                }}
              >
                {actionInFlight === 'cancel' || cascadeCancelling
                  ? 'Cancelling…'
                  : '✕ Cancel cascade'}
              </button>
            ) : (
              <button
                type="button"
                onClick={handleRunAll}
                disabled={!guidelineId || actionInFlight === 'run-all'}
                style={{
                  padding: '6px 14px',
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'white',
                  backgroundColor:
                    !guidelineId || actionInFlight === 'run-all' ? '#9CA3AF' : '#4F46E5',
                  border: 'none',
                  borderRadius: 4,
                  cursor:
                    !guidelineId || actionInFlight === 'run-all' ? 'not-allowed' : 'pointer',
                }}
              >
                {actionInFlight === 'run-all' ? 'Starting…' : '▶ Run all'}
              </button>
            )}
          </div>
        </div>

        {/* Cross-DAG warnings — stacked above the cascade halo because the
            warning is durable (until admin reruns explanations) while the
            cascade halo is ephemeral. */}
        {warnings.map((warning, idx) => {
          const rerunInFlight = actionInFlight === 'rerun:explanations';
          const explanationsRow = stageRowById['explanations'];
          const explanationsRunning = explanationsRow?.state === 'running';
          const buttonDisabled =
            !guidelineId || rerunInFlight || explanationsRunning;
          return (
            <div
              key={`${warning.kind}-${idx}`}
              data-testid="cross-dag-warning"
              style={{
                padding: '8px 12px',
                fontSize: 12,
                color: '#92400E',
                backgroundColor: '#FFFBEB',
                border: '1px solid #FCD34D',
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                flexWrap: 'wrap',
              }}
            >
              <span style={{ fontWeight: 600 }}>⚠ {warning.message}</span>
              {warning.last_explanations_at && (
                <span style={{ color: '#78350F' }}>
                  Last explanations: {formatRelativeTime(warning.last_explanations_at)}
                </span>
              )}
              <button
                type="button"
                onClick={() => handleRerun('explanations')}
                disabled={buttonDisabled}
                style={{
                  marginLeft: 'auto',
                  padding: '4px 10px',
                  fontSize: 12,
                  fontWeight: 600,
                  color: 'white',
                  backgroundColor: buttonDisabled ? '#9CA3AF' : '#D97706',
                  border: 'none',
                  borderRadius: 4,
                  cursor: buttonDisabled ? 'not-allowed' : 'pointer',
                }}
              >
                {rerunInFlight
                  ? 'Starting…'
                  : explanationsRunning
                    ? 'Explanations running…'
                    : '▶ Rerun explanations'}
              </button>
            </div>
          );
        })}

        {/* Cascade halo banner */}
        {cascadeActive && cascade && (
          <div
            style={{
              padding: '8px 12px',
              fontSize: 12,
              color: '#1E40AF',
              backgroundColor: '#EFF6FF',
              border: '1px solid #93C5FD',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <span style={{ fontWeight: 600 }}>
              Cascade {cascade.cascade_id.slice(0, 8)}…
            </span>
            <span>
              Running: <code>{cascade.running ?? '—'}</code>
            </span>
            <span>
              Remaining: {remainingStages.length}
              {remainingStages.length > 0 && (
                <code style={{ marginLeft: 4 }}>{remainingStages.join(', ')}</code>
              )}
            </span>
            {cascade.cancelled && (
              <span style={{ color: '#92400E', fontWeight: 600 }}>Cancelled</span>
            )}
          </div>
        )}

        {/* Resolve / fetch error */}
        {resolveError && (
          <div
            style={{
              padding: '8px 12px',
              fontSize: 12,
              color: '#991B1B',
              backgroundColor: '#FEF2F2',
              border: '1px solid #FCA5A5',
              borderRadius: 6,
            }}
          >
            {resolveError}
          </div>
        )}

        {/* Toast for action feedback */}
        {toast && (
          <div
            style={{
              padding: '8px 12px',
              fontSize: 12,
              color:
                toast.kind === 'error'
                  ? '#991B1B'
                  : toast.kind === 'warn'
                    ? '#92400E'
                    : '#065F46',
              backgroundColor:
                toast.kind === 'error'
                  ? '#FEF2F2'
                  : toast.kind === 'warn'
                    ? '#FFFBEB'
                    : '#ECFDF5',
              border: `1px solid ${
                toast.kind === 'error'
                  ? '#FCA5A5'
                  : toast.kind === 'warn'
                    ? '#FCD34D'
                    : '#6EE7B7'
              }`,
              borderRadius: 6,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span>{toast.message}</span>
            <button
              type="button"
              onClick={() => setToast(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                padding: 0,
                fontSize: 14,
              }}
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )}
      </div>

      {/* DAG canvas + side panel */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {!definition || !dag ? (
            <div
              style={{
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#6B7280',
                fontSize: 13,
              }}
            >
              Loading pipeline…
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1.0 }}
              minZoom={0.3}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
            >
              <Background color="#E5E7EB" gap={24} size={1} />
              <Controls />
            </ReactFlow>
          )}
        </div>

        {/* Side panel */}
        {selectedRow && selectedDef && (
          <SidePanel
            row={selectedRow}
            definition={selectedDef}
            bookId={bookId!}
            chapterId={chapterId!}
            cascadeActive={cascadeActive}
            stageRunning={stageRunning}
            actionInFlight={actionInFlight}
            onClose={() => setSelectedStageId(null)}
            onRerun={handleRerun}
            navigate={navigate}
          />
        )}
      </div>
    </div>
  );
};

// ───────── Side panel ─────────

interface SidePanelProps {
  row: TopicDAGStageRow;
  definition: { id: string; label: string; depends_on: string[] };
  bookId: string;
  chapterId: string;
  cascadeActive: boolean;
  stageRunning: boolean;
  actionInFlight: string | null;
  onClose: () => void;
  onRerun: (stageId: string) => void;
  navigate: (path: string) => void;
}

const STAGE_DEEP_LINK: Record<string, (b: string, c: string) => string> = {
  explanations: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  baatcheet_dialogue: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  baatcheet_visuals: (b, c) => `/admin/books-v2/${b}/explanations/${c}`,
  visuals: (b, c) => `/admin/books-v2/${b}/visuals/${c}`,
  practice_bank: (b, c) => `/admin/books-v2/${b}/practice-banks/${c}`,
};

function SidePanel({
  row,
  definition,
  bookId,
  chapterId,
  cascadeActive,
  stageRunning,
  actionInFlight,
  onClose,
  onRerun,
  navigate,
}: SidePanelProps) {
  const style = STATE_STYLE[row.state];
  const deepLink = STAGE_DEEP_LINK[row.stage_id]?.(bookId, chapterId);
  const rerunDisabled = stageRunning || cascadeActive || actionInFlight != null;

  return (
    <aside
      style={{
        width: 360,
        borderLeft: '1px solid #E5E7EB',
        backgroundColor: 'white',
        overflowY: 'auto',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #E5E7EB',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#111827' }}>
            {definition.label}
          </div>
          <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
            <code>{row.stage_id}</code>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: '#6B7280',
            cursor: 'pointer',
            fontSize: 18,
            padding: 0,
          }}
          aria-label="Close panel"
        >
          ×
        </button>
      </div>

      <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* State */}
        <div>
          <div style={{ fontSize: 10, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>
            State
          </div>
          <span
            style={{
              display: 'inline-block',
              padding: '3px 10px',
              fontSize: 12,
              fontWeight: 600,
              color: style.fg,
              backgroundColor: style.bg,
              border: `1px solid ${style.border}`,
              borderRadius: 999,
            }}
          >
            {style.label}
          </span>
          {row.is_stale && (
            <span
              style={{
                marginLeft: 6,
                display: 'inline-block',
                padding: '3px 10px',
                fontSize: 11,
                fontWeight: 600,
                color: '#92400E',
                backgroundColor: '#FEF3C7',
                border: '1px solid #FBBF24',
                borderRadius: 999,
              }}
              title="Marked stale by an upstream rerun"
            >
              STALE
            </span>
          )}
        </div>

        {/* Depends on */}
        {definition.depends_on.length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>
              Depends on
            </div>
            <div style={{ fontSize: 12, color: '#374151' }}>
              {definition.depends_on.map((d) => (
                <code key={d} style={{ marginRight: 6 }}>{d}</code>
              ))}
            </div>
          </div>
        )}

        {/* Timing */}
        {(row.started_at || row.completed_at || row.duration_ms) && (
          <div>
            <div style={{ fontSize: 10, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>
              Timing
            </div>
            <div style={{ fontSize: 12, color: '#374151', lineHeight: 1.6 }}>
              {row.duration_ms != null && <div>Duration: {formatDuration(row.duration_ms)}</div>}
              {row.started_at && (
                <div>
                  Started: {parseBackendDatetime(row.started_at).toLocaleString()} ({formatRelativeTime(row.started_at)})
                </div>
              )}
              {row.completed_at && (
                <div>
                  Completed: {parseBackendDatetime(row.completed_at).toLocaleString()} ({formatRelativeTime(row.completed_at)})
                </div>
              )}
            </div>
          </div>
        )}

        {/* Job id */}
        {row.last_job_id && (
          <div>
            <div style={{ fontSize: 10, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>
              Last job
            </div>
            <code style={{ fontSize: 11, color: '#374151' }}>{row.last_job_id}</code>
          </div>
        )}

        {/* Summary */}
        {row.summary && Object.keys(row.summary).length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>
              Summary
            </div>
            <pre
              style={{
                fontSize: 11,
                color: '#374151',
                backgroundColor: '#F9FAFB',
                border: '1px solid #E5E7EB',
                borderRadius: 6,
                padding: 8,
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {JSON.stringify(row.summary, null, 2)}
            </pre>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 8 }}>
          <button
            type="button"
            onClick={() => onRerun(row.stage_id)}
            disabled={rerunDisabled}
            title={
              stageRunning
                ? 'Stage is running'
                : cascadeActive
                  ? 'A cascade is active — wait or cancel first'
                  : 'Re-run this stage and cascade descendants'
            }
            style={{
              padding: '8px 12px',
              fontSize: 13,
              fontWeight: 600,
              color: 'white',
              backgroundColor: rerunDisabled ? '#9CA3AF' : '#4F46E5',
              border: 'none',
              borderRadius: 4,
              cursor: rerunDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            {actionInFlight === `rerun:${row.stage_id}`
              ? 'Starting…'
              : '↻ Rerun (cascade descendants)'}
          </button>
          {deepLink && (
            <button
              type="button"
              onClick={() => navigate(deepLink)}
              style={{
                padding: '8px 12px',
                fontSize: 13,
                color: '#374151',
                backgroundColor: '#F3F4F6',
                border: '1px solid #D1D5DB',
                borderRadius: 4,
                cursor: 'pointer',
              }}
            >
              Open stage admin →
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

export default TopicDAGView;
