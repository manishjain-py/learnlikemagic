/**
 * Interactive Visuals PoC — Test interactive templates with editable JSON params.
 *
 * Renders templates in a sandboxed iframe (same path as production VisualExplanation.tsx).
 * Admin selects a preset or edits params JSON, clicks Render, and sees the interactive visual.
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';

const TEMPLATES: Record<string, string> = {
  'drag-between-containers': '/templates/drag-between-containers.js',
};

interface Preset {
  label: string;
  template: string;
  params: object;
}

const PRESETS: Preset[] = [
  {
    label: 'Addition: Make 10',
    template: 'drag-between-containers',
    params: {
      title: 'Move 1 apple to make 10!',
      objects: [{ shape: 'circle', color: '0x4ECDC4', label: '\uD83C\uDF4E', count: 10 }],
      containers: [
        { label: 'Group', initial: 9 },
        { label: 'Extra', initial: 1 },
      ],
      goal: { Group: 10 },
      success_message: '9 + 1 = 10!',
    },
  },
  {
    label: 'Subtraction: Take away 2',
    template: 'drag-between-containers',
    params: {
      title: 'Take away 2 stars!',
      objects: [{ shape: 'circle', color: '0xFFD93D', label: '\u2B50', count: 5 }],
      containers: [
        { label: 'Stars', initial: 5 },
        { label: 'Removed', initial: 0 },
      ],
      goal: { Removed: 2 },
      success_message: '5 \u2212 2 = 3!',
    },
  },
  {
    label: 'Division: Equal groups',
    template: 'drag-between-containers',
    params: {
      title: 'Split into 2 equal groups!',
      objects: [{ shape: 'circle', color: '0xFF6B6B', label: '\uD83D\uDD34', count: 6 }],
      containers: [
        { label: 'All', initial: 6 },
        { label: 'Group 1', initial: 0 },
        { label: 'Group 2', initial: 0 },
      ],
      goal: { 'Group 1': 3, 'Group 2': 3 },
      success_message: '6 \u00F7 2 = 3 in each group!',
    },
  },
  {
    label: 'Comparison: More or fewer?',
    template: 'drag-between-containers',
    params: {
      title: 'Make both boxes equal!',
      objects: [{ shape: 'circle', color: '0xA78BFA', label: '\uD83D\uDFE3', count: 6 }],
      containers: [
        { label: 'Box A', initial: 4 },
        { label: 'Box B', initial: 2 },
      ],
      goal: { 'Box A': 3, 'Box B': 3 },
      success_message: '3 = 3 \u2014 Equal!',
    },
  },
];

// Build sandboxed iframe srcdoc (mirrors VisualExplanation.tsx pattern)
function buildSrcdoc(templateCode: string, params: object): string {
  return `<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; }
  body { background: #1a1a2e; overflow: hidden; touch-action: none; user-select: none; }
  canvas { display: block; width: 100% !important; height: auto !important; }
</style>
</head>
<body>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pixi.js/8.6.6/pixi.min.js"><\/script>
<script>
(async function() {
  try {
    var app = new PIXI.Application();
    await app.init({ width: 500, height: 350, backgroundColor: 0x1a1a2e, antialias: true });
    document.body.appendChild(app.canvas);
    var params = ${JSON.stringify(params)};
    var fn = new Function('app', 'PIXI', 'params', ${JSON.stringify(templateCode)});
    fn(app, PIXI, params);
    window.parent.postMessage({ type: 'pixi-ready' }, '*');
  } catch (e) {
    window.parent.postMessage({ type: 'pixi-error', message: e.message || String(e) }, '*');
  }
})();
<\/script>
</body>
</html>`;
}

const InteractiveVisualsPocPage: React.FC = () => {
  const [selectedPreset, setSelectedPreset] = useState(0);
  const [paramsJson, setParamsJson] = useState(JSON.stringify(PRESETS[0].params, null, 2));
  const [templateId, setTemplateId] = useState(PRESETS[0].template);
  const [srcdoc, setSrcdoc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);
  const [templateCode, setTemplateCode] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Listen for postMessage from iframe
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'pixi-error') {
        setError(`Render error: ${event.data.message}`);
      } else if (event.data?.type === 'pixi-ready') {
        setError(null);
      } else if (event.data?.type === 'interaction-complete') {
        const r = event.data.result;
        setResult(r.correct ? 'Correct!' : `Incorrect \u2014 counts: ${JSON.stringify(r.counts)}`);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  const handlePresetChange = useCallback((index: number) => {
    setSelectedPreset(index);
    setTemplateId(PRESETS[index].template);
    setParamsJson(JSON.stringify(PRESETS[index].params, null, 2));
    setSrcdoc(null);
    setError(null);
    setResult(null);
  }, []);

  const handleRender = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSrcdoc(null);

    try {
      // Validate JSON
      const params = JSON.parse(paramsJson);

      // Fetch template code
      const templatePath = TEMPLATES[templateId];
      if (!templatePath) throw new Error(`Unknown template: ${templateId}`);

      const resp = await fetch(templatePath);
      if (!resp.ok) throw new Error(`Failed to load template: ${resp.statusText}`);
      const code = await resp.text();
      setTemplateCode(code);

      // Build srcdoc and render
      const doc = buildSrcdoc(code, params);
      setSrcdoc(doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to render');
    } finally {
      setLoading(false);
    }
  }, [paramsJson, templateId]);

  const handleReset = useCallback(() => {
    // Force iframe re-render by clearing and re-setting srcdoc
    const currentSrcdoc = srcdoc;
    setSrcdoc(null);
    setResult(null);
    if (currentSrcdoc) {
      queueMicrotask(() => setSrcdoc(currentSrcdoc));
    }
  }, [srcdoc]);

  return (
    <div style={{ padding: '20px', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: '600', marginBottom: '6px' }}>
          Interactive Visuals PoC
        </h1>
        <p style={{ color: '#6B7280', fontSize: '13px' }}>
          Test interactive templates with editable params. Renders in a sandboxed iframe (same as production).
        </p>
      </div>

      <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-start' }}>
        {/* Left panel: controls */}
        <div style={{ width: '480px', flexShrink: 0 }}>
          {/* Preset selector */}
          <div style={{ marginBottom: '16px' }}>
            <label style={{ fontSize: '13px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '6px' }}>
              Preset Examples
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {PRESETS.map((preset, i) => (
                <button
                  key={i}
                  onClick={() => handlePresetChange(i)}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: '1px solid ' + (selectedPreset === i ? '#6C63FF' : '#D1D5DB'),
                    backgroundColor: selectedPreset === i ? '#EEF2FF' : 'white',
                    color: selectedPreset === i ? '#6C63FF' : '#374151',
                    fontSize: '12px',
                    fontWeight: selectedPreset === i ? 600 : 400,
                    cursor: 'pointer',
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Template selector */}
          <div style={{ marginBottom: '12px' }}>
            <label style={{ fontSize: '13px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
              Template
            </label>
            <select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #D1D5DB',
                fontSize: '13px',
                backgroundColor: 'white',
                boxSizing: 'border-box',
              }}
            >
              {Object.keys(TEMPLATES).map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>

          {/* JSON params editor */}
          <div style={{ marginBottom: '12px' }}>
            <label style={{ fontSize: '13px', fontWeight: '600', color: '#374151', display: 'block', marginBottom: '4px' }}>
              Params (JSON)
            </label>
            <textarea
              value={paramsJson}
              onChange={(e) => setParamsJson(e.target.value)}
              spellCheck={false}
              style={{
                width: '100%',
                height: '260px',
                padding: '10px',
                borderRadius: '6px',
                border: '1px solid #D1D5DB',
                fontSize: '12px',
                fontFamily: 'monospace',
                resize: 'vertical',
                boxSizing: 'border-box',
                lineHeight: '1.5',
              }}
            />
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
            <button
              onClick={handleRender}
              disabled={loading}
              style={{
                padding: '8px 20px',
                backgroundColor: loading ? '#93C5FD' : '#6C63FF',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                fontSize: '13px',
                fontWeight: '600',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Loading...' : 'Render'}
            </button>
            {srcdoc && (
              <button
                onClick={handleReset}
                style={{
                  padding: '8px 16px',
                  backgroundColor: 'white',
                  color: '#374151',
                  border: '1px solid #D1D5DB',
                  borderRadius: '6px',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                Reset
              </button>
            )}
            {templateCode && (
              <button
                onClick={() => setShowCode(!showCode)}
                style={{
                  padding: '8px 16px',
                  backgroundColor: 'white',
                  color: '#374151',
                  border: '1px solid #D1D5DB',
                  borderRadius: '6px',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
              >
                {showCode ? 'Hide Code' : 'Show Code'}
              </button>
            )}
          </div>

          {/* Error */}
          {error && (
            <div style={{
              padding: '10px 14px',
              backgroundColor: '#FEF2F2',
              color: '#991B1B',
              borderRadius: '6px',
              fontSize: '13px',
              marginBottom: '12px',
            }}>
              {error}
            </div>
          )}

          {/* Interaction result */}
          {result && (
            <div style={{
              padding: '10px 14px',
              backgroundColor: result.startsWith('Correct') ? '#F0FDF4' : '#FEF2F2',
              color: result.startsWith('Correct') ? '#166534' : '#991B1B',
              borderRadius: '6px',
              fontSize: '13px',
              marginBottom: '12px',
            }}>
              postMessage received: {result}
            </div>
          )}
        </div>

        {/* Right panel: canvas */}
        <div style={{ flex: 1, minWidth: '520px' }}>
          <div style={{
            width: '500px',
            height: '350px',
            borderRadius: '10px',
            overflow: 'hidden',
            backgroundColor: '#1a1a2e',
            border: '1px solid #374151',
            position: 'relative',
          }}>
            {!srcdoc && !loading && (
              <div style={{
                position: 'absolute', inset: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <p style={{ color: '#6B7280', fontSize: '13px' }}>
                  Select a preset and click Render
                </p>
              </div>
            )}
            {loading && (
              <div style={{
                position: 'absolute', inset: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <p style={{ color: '#93C5FD', fontSize: '13px' }}>Loading template...</p>
              </div>
            )}
            {srcdoc && (
              <iframe
                ref={iframeRef}
                sandbox="allow-scripts"
                srcDoc={srcdoc}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                title="Interactive visual preview"
              />
            )}
          </div>

          {/* Template code (collapsible) */}
          {showCode && templateCode && (
            <div style={{ marginTop: '12px' }}>
              <pre style={{
                padding: '14px',
                backgroundColor: '#1E293B',
                color: '#E2E8F0',
                borderRadius: '8px',
                fontSize: '11px',
                overflow: 'auto',
                maxHeight: '300px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {templateCode}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default InteractiveVisualsPocPage;
