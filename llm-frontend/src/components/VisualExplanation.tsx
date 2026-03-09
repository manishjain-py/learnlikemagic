import { useState, useRef, useCallback, useEffect } from 'react';
import { Application } from 'pixi.js';
import type { VisualExplanation as VisualExplanationType } from '../api';

interface Props {
  visual: VisualExplanationType;
}

export default function VisualExplanation({ visual }: Props) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<Application | null>(null);

  const destroyPixiApp = useCallback(() => {
    if (pixiAppRef.current) {
      pixiAppRef.current.destroy(true);
      pixiAppRef.current = null;
    }
    if (canvasContainerRef.current) {
      canvasContainerRef.current.innerHTML = '';
    }
  }, []);

  useEffect(() => {
    return () => {
      destroyPixiApp();
    };
  }, [destroyPixiApp]);

  const executePixiCode = useCallback(async (code: string) => {
    destroyPixiApp();
    setError(null);

    if (!canvasContainerRef.current || !code) return;

    try {
      const app = new Application();
      await app.init({
        width: 500,
        height: 350,
        backgroundColor: 0x1a1a2e,
        antialias: true,
      });

      canvasContainerRef.current.appendChild(app.canvas);
      pixiAppRef.current = app;

      const PIXI = await import('pixi.js');
      (window as any).PIXI = PIXI;

      const fn = new Function('app', 'PIXI', code);
      fn(app, PIXI);
    } catch (err) {
      console.error('Pixi.js execution error:', err);
      setError('Visual could not be loaded');
    }
  }, [destroyPixiApp]);

  const startAnimation = useCallback(() => {
    setStarted(true);
    if (visual.pixi_code) {
      executePixiCode(visual.pixi_code);
    }
  }, [visual.pixi_code, executePixiCode]);

  const replay = useCallback(() => {
    if (visual.pixi_code) {
      executePixiCode(visual.pixi_code);
    }
  }, [visual.pixi_code, executePixiCode]);

  if (!visual.pixi_code) {
    return null;
  }

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
      <div className="visual-canvas-pixi" ref={canvasContainerRef} />
      {error && <div className="visual-error">{error}</div>}
      {visual.narration && <div className="visual-narration">{visual.narration}</div>}
      <button className="visual-replay-btn" onClick={replay} title="Replay">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="1 4 1 10 7 10" />
          <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
        </svg>
        Replay
      </button>
    </div>
  );
}
