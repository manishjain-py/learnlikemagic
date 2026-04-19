/**
 * Admin-only preview route for the Visual Rendering Review pipeline.
 *
 * Security design:
 *  - The pixi code is loaded from GET /admin/v2/visual-preview/{id}, NOT from
 *    the URL. The URL carries only the id, useless without a matching
 *    server-side entry. Entries expire after ~2 minutes (server-side TTL).
 *    This closes the reflected-XSS vector where a crafted ?code=... URL
 *    could execute arbitrary JS in an admin session.
 *
 * Differences from student-facing VisualExplanation.tsx:
 *  - Mounts Pixi directly on the page (no sandboxed iframe) so Playwright
 *    can reach into window.__pixiApp.stage via page.evaluate(). The
 *    student-facing component uses a sandboxed iframe for defense in
 *    depth — see docs/feature-development/ingestion-quality-reviews/
 *    impl-plan.md §3.3 for the trade-off rationale.
 *  - Signals render state via a `data-pixi-state` attribute on the canvas
 *    container so Playwright can wait for it to flip to "ready" or "error".
 *
 * Admin-only. Never served to students. Never call window.__pixiApp from
 * a student-facing code path.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Application } from 'pixi.js';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

type RenderState = 'loading' | 'ready' | 'error';

export default function VisualRenderPreview() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<RenderState>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<Application | null>(null);

  useEffect(() => {
    if (!id || !canvasContainerRef.current) return;

    let cancelled = false;

    const bootPixi = async () => {
      try {
        const res = await fetch(
          `${API_BASE_URL}/admin/v2/visual-preview/${encodeURIComponent(id)}`
        );
        if (!res.ok) {
          throw new Error(`preview fetch failed: HTTP ${res.status}`);
        }
        const { pixi_code: code, output_type: outputType } = (await res.json()) as {
          pixi_code: string;
          output_type: string;
        };

        if (cancelled || !canvasContainerRef.current) return;

        const app = new Application();
        await app.init({
          width: 500,
          height: 350,
          backgroundColor: 0x1a1a2e,
          antialias: true,
        });
        canvasContainerRef.current.appendChild(app.canvas);
        pixiAppRef.current = app;

        // Expose for Playwright's page.evaluate().
        (window as any).__pixiApp = app;

        // Make PIXI available globally for the generated code.
        const PIXI = await import('pixi.js');
        (window as any).PIXI = PIXI;

        // Execute the generated code with `app` in scope.
        const fn = new Function('app', 'PIXI', code);
        fn(app, PIXI);

        // For animated visuals, wait for the 2+s end-state pause to settle
        // before marking ready so the screenshot captures the end state.
        const waitMs = outputType === 'animated_visual' ? 8000 : 500;
        setTimeout(() => {
          if (!cancelled) setState('ready');
        }, waitMs);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        (window as any).__pixiError = msg;
        if (!cancelled) {
          setErrorMessage(msg);
          setState('error');
        }
      }
    };

    bootPixi();

    return () => {
      cancelled = true;
      if (pixiAppRef.current) {
        pixiAppRef.current.destroy(true);
        pixiAppRef.current = null;
      }
      if (canvasContainerRef.current) {
        canvasContainerRef.current.innerHTML = '';
      }
    };
  }, [id]);

  return (
    <div style={{ padding: 16, backgroundColor: '#111', color: '#eee', minHeight: '100vh' }}>
      <div
        ref={canvasContainerRef}
        data-pixi-state={state}
        style={{ width: 500, height: 350, backgroundColor: '#1a1a2e', margin: '0 auto' }}
      />
      {state === 'error' && (
        <div style={{ marginTop: 16, color: '#f87171', fontFamily: 'monospace', fontSize: 12 }}>
          Render error: {errorMessage}
        </div>
      )}
      <div style={{ marginTop: 12, fontSize: 11, color: '#888', textAlign: 'center' }}>
        Admin preview for render harness — state: {state}
      </div>
    </div>
  );
}
