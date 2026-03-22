import { useState, useCallback, useEffect, useRef } from 'react';
import type { VisualExplanation as VisualExplanationType } from '../api';

interface Props {
  visual: VisualExplanationType;
}

/**
 * Renders LLM-generated Pixi.js visuals inside a sandboxed iframe.
 *
 * The iframe has `sandbox="allow-scripts"` — no access to parent page DOM,
 * cookies, localStorage, or navigation. This mitigates XSS risk from
 * executing LLM-generated code.
 */
export default function VisualExplanation({ visual }: Props) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  const pixiCode = visual.pixi_code;
  const hasLegacyFormat = !!visual.scene_type;

  // Build the srcdoc HTML that runs inside the sandboxed iframe.
  // Pixi.js is loaded from CDN inside the iframe — no global pollution on the parent.
  const buildSrcdoc = useCallback((code: string) => {
    return `<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; }
  body { background: #1a1a2e; overflow: hidden; }
  canvas { display: block; width: 100% !important; height: auto !important; }
</style>
</head>
<body>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pixi.js/8.6.6/pixi.min.js"><\/script>
<script>
(async function() {
  try {
    const app = new PIXI.Application();
    await app.init({ width: 500, height: 350, backgroundColor: 0x1a1a2e, antialias: true });
    document.body.appendChild(app.canvas);
    const fn = new Function('app', 'PIXI', ${JSON.stringify(code)});
    fn(app, PIXI);
    window.parent.postMessage({ type: 'pixi-ready' }, '*');
  } catch (e) {
    window.parent.postMessage({ type: 'pixi-error', message: e.message || String(e) }, '*');
  }
})();
<\/script>
</body>
</html>`;
  }, []);

  // Listen for messages from the sandboxed iframe
  useEffect(() => {
    if (!started) return;

    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'pixi-error') {
        setError('Visual could not be loaded');
        console.error('Pixi.js iframe error:', event.data.message);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [started]);

  // Reset state when pixi_code changes (prop change cleanup)
  useEffect(() => {
    setStarted(false);
    setError(null);
  }, [pixiCode]);

  const startAnimation = useCallback(() => {
    setStarted(true);
    setError(null);
    // Scroll the visual into view after rendering
    requestAnimationFrame(() => {
      canvasRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  const replay = useCallback(() => {
    // Force iframe re-render by toggling started
    setStarted(false);
    setError(null);
    queueMicrotask(() => setStarted(true));
  }, []);

  // Backward compat: old sessions have scene_type but no pixi_code — skip rendering
  if (!pixiCode || hasLegacyFormat) {
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
    <div className="visual-explanation" ref={canvasRef}>
      {visual.title && <div className="visual-title">{visual.title}</div>}
      <div className="visual-canvas-pixi">
        <iframe
          sandbox="allow-scripts"
          srcDoc={buildSrcdoc(pixiCode)}
          style={{ width: '100%', aspectRatio: '500 / 350', border: 'none', display: 'block' }}
          title={visual.title || 'Visual explanation'}
        />
      </div>
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
