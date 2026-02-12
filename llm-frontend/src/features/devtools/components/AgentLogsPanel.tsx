import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { AgentLogEntry } from '../types';
import { getAgentLogs } from '../api/devToolsApi';

interface Props {
  sessionId: string;
}

const AGENT_COLORS: Record<string, string> = {
  master_tutor: '#667eea',
  grader: '#e65100',
  planner: '#2e7d32',
  evaluator: '#c62828',
  router: '#00838f',
};

function getAgentColor(name: string): string {
  return AGENT_COLORS[name] || '#777';
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100%',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '12px 16px',
    borderBottom: '1px solid #e0e0e0',
    background: '#fafafa',
    flexWrap: 'wrap' as const,
  },
  select: {
    padding: '4px 8px',
    borderRadius: '4px',
    border: '1px solid #ccc',
    fontSize: '0.8rem',
    background: 'white',
  },
  refreshBtn: {
    padding: '4px 10px',
    borderRadius: '4px',
    border: '1px solid #ccc',
    background: 'white',
    cursor: 'pointer',
    fontSize: '0.8rem',
    marginLeft: 'auto',
  } as React.CSSProperties,
  scrollArea: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '12px 16px',
  },
  turnGroup: {
    marginBottom: '16px',
  },
  turnHeader: {
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#888',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: '6px',
    paddingBottom: '4px',
    borderBottom: '1px solid #eee',
  },
  logEntry: {
    padding: '8px 10px',
    marginBottom: '4px',
    borderRadius: '6px',
    background: '#f9f9f9',
    cursor: 'pointer',
  } as React.CSSProperties,
  logTopRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    flexWrap: 'wrap' as const,
  },
  agentBadge: (color: string) =>
    ({
      display: 'inline-block',
      padding: '1px 6px',
      borderRadius: '3px',
      fontSize: '0.7rem',
      fontWeight: 600,
      background: color + '18',
      color: color,
    }) as React.CSSProperties,
  eventType: {
    fontSize: '0.8rem',
    fontWeight: 500,
    color: '#333',
  },
  modelBadge: {
    display: 'inline-block',
    padding: '1px 5px',
    borderRadius: '3px',
    fontSize: '0.65rem',
    fontWeight: 500,
    background: '#e8e8e8',
    color: '#666',
  },
  duration: {
    fontSize: '0.75rem',
    color: '#999',
  },
  timestamp: {
    fontSize: '0.7rem',
    color: '#bbb',
    marginLeft: 'auto',
  } as React.CSSProperties,
  expandedSection: {
    marginTop: '8px',
  },
  sectionLabel: {
    fontSize: '0.7rem',
    fontWeight: 600,
    color: '#888',
    textTransform: 'uppercase' as const,
    marginTop: '8px',
    marginBottom: '4px',
  },
  pre: {
    background: '#1e1e1e',
    color: '#d4d4d4',
    padding: '10px',
    borderRadius: '4px',
    fontSize: '0.75rem',
    overflow: 'auto' as const,
    maxHeight: '300px',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
    lineHeight: 1.4,
  } as React.CSSProperties,
  textBlock: {
    fontSize: '0.8rem',
    color: '#444',
    lineHeight: 1.5,
    background: '#f5f5f5',
    padding: '8px 10px',
    borderRadius: '4px',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  } as React.CSSProperties,
  empty: {
    padding: '24px',
    textAlign: 'center' as const,
    color: '#999',
    fontSize: '0.9rem',
  },
  loading: {
    padding: '24px',
    textAlign: 'center' as const,
    color: '#666',
    fontSize: '0.85rem',
  },
};

export default function AgentLogsPanel({ sessionId }: Props) {
  const [logs, setLogs] = useState<AgentLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [filterAgent, setFilterAgent] = useState('');
  const [filterTurn, setFilterTurn] = useState('');

  const fetchLogs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const filters: { turn_id?: string; agent_name?: string } = {};
      if (filterAgent) filters.agent_name = filterAgent;
      if (filterTurn) filters.turn_id = filterTurn;
      const resp = await getAgentLogs(sessionId, filters);
      setLogs(resp.logs);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch logs');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, filterAgent, filterTurn]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Extract unique agents and turns for filter dropdowns
  const uniqueAgents = useMemo(
    () => [...new Set(logs.map((l) => l.agent_name))].sort(),
    [logs]
  );
  const uniqueTurns = useMemo(
    () => [...new Set(logs.map((l) => l.turn_id))].sort(),
    [logs]
  );

  // Group logs by turn_id
  const grouped = useMemo(() => {
    const map = new Map<string, AgentLogEntry[]>();
    for (const log of logs) {
      const key = log.turn_id || 'unknown';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(log);
    }
    return map;
  }, [logs]);

  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString();
    } catch {
      return iso;
    }
  };

  // Compute a global index for each log entry (for expandedIdx)
  const flatEntries: { turnId: string; entry: AgentLogEntry; globalIdx: number }[] = useMemo(() => {
    const result: { turnId: string; entry: AgentLogEntry; globalIdx: number }[] = [];
    let idx = 0;
    for (const [turnId, entries] of grouped) {
      for (const entry of entries) {
        result.push({ turnId, entry, globalIdx: idx });
        idx++;
      }
    }
    return result;
  }, [grouped]);

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <select
          style={styles.select}
          value={filterAgent}
          onChange={(e) => setFilterAgent(e.target.value)}
        >
          <option value="">All agents</option>
          {uniqueAgents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          style={styles.select}
          value={filterTurn}
          onChange={(e) => setFilterTurn(e.target.value)}
        >
          <option value="">All turns</option>
          {uniqueTurns.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button
          style={styles.refreshBtn}
          onClick={fetchLogs}
          disabled={isLoading}
        >
          {isLoading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div style={styles.scrollArea}>
        {error && (
          <div style={{ ...styles.empty, color: '#c62828' }}>{error}</div>
        )}

        {!error && logs.length === 0 && !isLoading && (
          <div style={styles.empty}>
            No agent logs yet. Send some messages first.
          </div>
        )}

        {isLoading && logs.length === 0 && (
          <div style={styles.loading}>Loading logs...</div>
        )}

        {[...grouped.entries()].map(([turnId, entries]) => (
          <div key={turnId} style={styles.turnGroup}>
            <div style={styles.turnHeader}>{turnId.replace('_', ' ')}</div>
            {entries.map((entry) => {
              const globalIdx = flatEntries.find(
                (f) => f.entry === entry
              )?.globalIdx;
              const isExpanded = expandedIdx === globalIdx;

              return (
                <div
                  key={globalIdx}
                  style={{
                    ...styles.logEntry,
                    background: isExpanded ? '#f0f0ff' : '#f9f9f9',
                  }}
                  onClick={() =>
                    setExpandedIdx(isExpanded ? null : globalIdx ?? null)
                  }
                >
                  <div style={styles.logTopRow}>
                    <span style={styles.agentBadge(getAgentColor(entry.agent_name))}>
                      {entry.agent_name}
                    </span>
                    <span style={styles.eventType}>{entry.event_type}</span>
                    {entry.model && (
                      <span style={styles.modelBadge}>{entry.model}</span>
                    )}
                    {entry.duration_ms != null && (
                      <span style={styles.duration}>
                        {entry.duration_ms}ms
                      </span>
                    )}
                    <span style={styles.timestamp}>
                      {formatTime(entry.timestamp)}
                    </span>
                  </div>

                  {isExpanded && (
                    <div style={styles.expandedSection}>
                      {entry.input_summary && (
                        <>
                          <div style={styles.sectionLabel}>Input Summary</div>
                          <div style={styles.textBlock}>
                            {entry.input_summary}
                          </div>
                        </>
                      )}
                      {entry.output && (
                        <>
                          <div style={styles.sectionLabel}>Output</div>
                          <pre style={styles.pre}>
                            {JSON.stringify(entry.output, null, 2)}
                          </pre>
                        </>
                      )}
                      {entry.reasoning && (
                        <>
                          <div style={styles.sectionLabel}>Reasoning</div>
                          <div style={styles.textBlock}>{entry.reasoning}</div>
                        </>
                      )}
                      {entry.prompt && (
                        <>
                          <div style={styles.sectionLabel}>Full Prompt</div>
                          <pre style={styles.pre}>{entry.prompt}</pre>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
