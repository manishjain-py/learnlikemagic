/**
 * Pixi.js PoC Page — Generate diagrams/animations from text prompts using LLM + Pixi.js v8.
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Application } from 'pixi.js';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface GenerateResponse {
  code: string;
  output_type: string;
}

const PixiJsPocPage: React.FC = () => {
  const [prompt, setPrompt] = useState('');
  const [outputType, setOutputType] = useState<'image' | 'animation'>('image');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);

  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<Application | null>(null);

  // Cleanup Pixi app on unmount
  useEffect(() => {
    return () => {
      if (pixiAppRef.current) {
        pixiAppRef.current.destroy(true);
        pixiAppRef.current = null;
      }
    };
  }, []);

  const destroyPixiApp = useCallback(() => {
    if (pixiAppRef.current) {
      pixiAppRef.current.destroy(true);
      pixiAppRef.current = null;
    }
    if (canvasContainerRef.current) {
      canvasContainerRef.current.innerHTML = '';
    }
  }, []);

  const executePixiCode = useCallback(async (code: string) => {
    destroyPixiApp();

    if (!canvasContainerRef.current) return;

    try {
      // Create new Pixi Application (v8 async init)
      const app = new Application();
      await app.init({
        width: 800,
        height: 600,
        backgroundColor: 0x1a1a2e,
        antialias: true,
      });

      canvasContainerRef.current.appendChild(app.canvas);
      pixiAppRef.current = app;

      // Make PIXI available globally for the generated code
      const PIXI = await import('pixi.js');
      (window as any).PIXI = PIXI;

      // Execute the generated code with `app` in scope
      const fn = new Function('app', 'PIXI', code);
      fn(app, PIXI);
    } catch (err) {
      console.error('Pixi.js execution error:', err);
      setError(`Code execution error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [destroyPixiApp]);

  const handleGenerate = useCallback(async () => {
    if (!prompt.trim()) return;

    setLoading(true);
    setError(null);
    setGeneratedCode(null);
    destroyPixiApp();

    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/pixi-poc/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt.trim(), output_type: outputType }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `API error: ${response.statusText}`);
      }

      const data: GenerateResponse = await response.json();
      setGeneratedCode(data.code);
      await executePixiCode(data.code);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setLoading(false);
    }
  }, [prompt, outputType, destroyPixiApp, executePixiCode]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleGenerate();
    }
  }, [handleGenerate]);

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '8px' }}>
          Pixi.js Diagram PoC
        </h1>
        <p style={{ color: '#6B7280', fontSize: '14px' }}>
          Describe a diagram or animation and the LLM will generate Pixi.js code to render it.
        </p>
      </div>

      {/* Input area */}
      <div style={{
        display: 'flex', gap: '16px', marginBottom: '20px',
        flexDirection: 'column',
      }}>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe what you want to draw... e.g., 'A solar system with the sun in the center and planets orbiting around it' or 'A bar chart showing sales data for Q1-Q4'"
          style={{
            width: '100%',
            minHeight: '100px',
            padding: '12px',
            borderRadius: '8px',
            border: '1px solid #D1D5DB',
            fontSize: '14px',
            fontFamily: 'inherit',
            resize: 'vertical',
            boxSizing: 'border-box',
          }}
        />

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          {/* Output type selector */}
          <div style={{ display: 'flex', gap: '4px', backgroundColor: '#F3F4F6', borderRadius: '8px', padding: '4px' }}>
            <button
              onClick={() => setOutputType('image')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                fontSize: '13px',
                fontWeight: '500',
                cursor: 'pointer',
                backgroundColor: outputType === 'image' ? '#3B82F6' : 'transparent',
                color: outputType === 'image' ? 'white' : '#6B7280',
              }}
            >
              Static Image
            </button>
            <button
              onClick={() => setOutputType('animation')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                fontSize: '13px',
                fontWeight: '500',
                cursor: 'pointer',
                backgroundColor: outputType === 'animation' ? '#3B82F6' : 'transparent',
                color: outputType === 'animation' ? 'white' : '#6B7280',
              }}
            >
              Animation
            </button>
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={loading || !prompt.trim()}
            style={{
              padding: '10px 24px',
              backgroundColor: loading || !prompt.trim() ? '#93C5FD' : '#3B82F6',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '500',
              cursor: loading || !prompt.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Generating...' : 'Generate (Ctrl+Enter)'}
          </button>

          {/* Toggle code view */}
          {generatedCode && (
            <button
              onClick={() => setShowCode(!showCode)}
              style={{
                padding: '10px 16px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '8px',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              {showCode ? 'Hide Code' : 'Show Code'}
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: '#FEF2F2',
          color: '#991B1B',
          borderRadius: '8px',
          marginBottom: '16px',
          fontSize: '14px',
        }}>
          {error}
        </div>
      )}

      {/* Generated code (collapsible) */}
      {showCode && generatedCode && (
        <div style={{ marginBottom: '16px' }}>
          <pre style={{
            padding: '16px',
            backgroundColor: '#1E293B',
            color: '#E2E8F0',
            borderRadius: '8px',
            fontSize: '12px',
            overflow: 'auto',
            maxHeight: '300px',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {generatedCode}
          </pre>
        </div>
      )}

      {/* Canvas area */}
      <div style={{
        width: '800px',
        height: '600px',
        borderRadius: '12px',
        overflow: 'hidden',
        backgroundColor: '#1a1a2e',
        border: '1px solid #374151',
        position: 'relative',
      }}>
        {!loading && !generatedCode && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <p style={{ color: '#6B7280', fontSize: '14px' }}>
              Your diagram will appear here
            </p>
          </div>
        )}
        {loading && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <p style={{ color: '#93C5FD', fontSize: '14px' }}>
              Generating Pixi.js code...
            </p>
          </div>
        )}
        <div ref={canvasContainerRef} style={{ width: '100%', height: '100%' }} />
      </div>
    </div>
  );
};

export default PixiJsPocPage;
