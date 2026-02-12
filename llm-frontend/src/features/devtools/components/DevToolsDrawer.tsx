import React, { useState, useEffect } from 'react';
import { SessionStateResponse } from '../types';
import { getSessionState } from '../api/devToolsApi';
import StudyPlanPanel from './StudyPlanPanel';
import GuidelinesPanel from './GuidelinesPanel';
import AgentLogsPanel from './AgentLogsPanel';

interface Props {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
}

type Tab = 'plan' | 'guidelines' | 'logs';

const DRAWER_WIDTH = 480;

const styles = {
  backdrop: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.3)',
    zIndex: 9998,
  },
  drawer: (isOpen: boolean) =>
    ({
      position: 'fixed' as const,
      top: 0,
      right: 0,
      width: `${DRAWER_WIDTH}px`,
      maxWidth: '100vw',
      height: '100vh',
      background: 'white',
      boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column' as const,
      transform: isOpen ? 'translateX(0)' : `translateX(${DRAWER_WIDTH}px)`,
      transition: 'transform 0.25s ease-in-out',
    }) as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid #e0e0e0',
    background: '#fafafa',
  } as React.CSSProperties,
  title: {
    fontSize: '0.95rem',
    fontWeight: 600,
    color: '#333',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: '1.2rem',
    cursor: 'pointer',
    color: '#666',
    padding: '4px 8px',
    borderRadius: '4px',
  } as React.CSSProperties,
  tabs: {
    display: 'flex',
    borderBottom: '1px solid #e0e0e0',
  } as React.CSSProperties,
  tab: (active: boolean) =>
    ({
      flex: 1,
      padding: '10px 8px',
      background: 'none',
      border: 'none',
      borderBottom: active ? '2px solid #667eea' : '2px solid transparent',
      cursor: 'pointer',
      fontSize: '0.8rem',
      fontWeight: active ? 600 : 400,
      color: active ? '#667eea' : '#888',
      transition: 'all 0.15s',
    }) as React.CSSProperties,
  content: {
    flex: 1,
    overflowY: 'auto' as const,
  },
  loading: {
    padding: '24px',
    textAlign: 'center' as const,
    color: '#666',
  } as React.CSSProperties,
  error: {
    padding: '24px',
    textAlign: 'center' as const,
    color: '#c62828',
    fontSize: '0.85rem',
  } as React.CSSProperties,
};

export default function DevToolsDrawer({ sessionId, isOpen, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('plan');
  const [sessionState, setSessionState] = useState<SessionStateResponse | null>(null);
  const [stateLoading, setStateLoading] = useState(false);
  const [stateError, setStateError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    let cancelled = false;
    setStateLoading(true);
    setStateError(null);

    getSessionState(sessionId)
      .then((data) => {
        if (!cancelled) setSessionState(data);
      })
      .catch((e) => {
        if (!cancelled)
          setStateError(e instanceof Error ? e.message : 'Failed to load session state');
      })
      .finally(() => {
        if (!cancelled) setStateLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, sessionId]);

  // Don't render anything when closed (but keep in DOM for animation)
  // We render the drawer always but translate it offscreen
  if (!isOpen) {
    return <div style={styles.drawer(false)} />;
  }

  return (
    <>
      <div style={styles.backdrop} onClick={onClose} />
      <div style={styles.drawer(true)}>
        <div style={styles.header}>
          <span style={styles.title}>Dev Tools</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close">
            &times;
          </button>
        </div>

        <div style={styles.tabs}>
          <button style={styles.tab(tab === 'plan')} onClick={() => setTab('plan')}>
            Study Plan
          </button>
          <button style={styles.tab(tab === 'guidelines')} onClick={() => setTab('guidelines')}>
            Guidelines
          </button>
          <button style={styles.tab(tab === 'logs')} onClick={() => setTab('logs')}>
            Agent Logs
          </button>
        </div>

        <div style={styles.content}>
          {tab === 'logs' ? (
            <AgentLogsPanel sessionId={sessionId} />
          ) : stateLoading ? (
            <div style={styles.loading}>Loading session state...</div>
          ) : stateError ? (
            <div style={styles.error}>{stateError}</div>
          ) : sessionState ? (
            tab === 'plan' ? (
              <StudyPlanPanel sessionState={sessionState} />
            ) : (
              <GuidelinesPanel sessionState={sessionState} />
            )
          ) : null}
        </div>
      </div>
    </>
  );
}
