/**
 * TTS Config Admin Page — single dropdown to flip the active TTS provider.
 * Mirrors the LLM provider toggle pattern but with the narrow TTS vocabulary
 * (google_tts | elevenlabs).
 */

import React, { useEffect, useState } from 'react';
import { getTTSConfig, updateTTSConfig } from '../api/adminApi';

const TTSConfigPage: React.FC = () => {
  const [provider, setProvider] = useState<string>('');
  const [available, setAvailable] = useState<string[]>([]);
  const [edit, setEdit] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getTTSConfig();
      setProvider(data.provider);
      setEdit(data.provider);
      setAvailable(data.available_providers);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load TTS config');
    } finally {
      setLoading(false);
    }
  };

  const changed = edit !== provider;

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await updateTTSConfig(edit);
      setProvider(edit);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '720px', margin: '0 auto' }}>
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          TTS Provider
        </h1>
        <p style={{ color: '#6B7280', lineHeight: 1.5 }}>
          Selects the speech synthesis provider for all student-facing audio
          (baatcheet dialogues, explanation cards, check-ins, runtime
          personalized cards). Changes take effect on the next synthesis
          call — no redeploy needed. Cached audio in S3 is not regenerated;
          use the Audio stage's force-rerun to refresh existing libraries.
        </p>
      </div>

      {error && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: '#FEF2F2',
          color: '#991B1B',
          borderRadius: '6px',
          marginBottom: '20px',
        }}>
          {error}
        </div>
      )}

      {loading ? (
        <p style={{ color: '#6B7280' }}>Loading…</p>
      ) : (
        <div style={{
          backgroundColor: 'white',
          borderRadius: '8px',
          padding: '20px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          flexWrap: 'wrap',
        }}>
          <label style={{ fontWeight: 600, fontSize: '14px' }}>Provider</label>
          <select
            value={edit}
            onChange={(e) => setEdit(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid #D1D5DB',
              fontSize: '14px',
              backgroundColor: changed ? '#FEF9C3' : 'white',
              minWidth: '180px',
            }}
          >
            {available.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          {saved ? (
            <span style={{ color: '#059669', fontSize: '14px', fontWeight: 500 }}>Saved</span>
          ) : (
            <button
              onClick={handleSave}
              disabled={!changed || saving}
              style={{
                padding: '8px 20px',
                backgroundColor: changed ? '#3B82F6' : '#E5E7EB',
                color: changed ? 'white' : '#9CA3AF',
                border: 'none',
                borderRadius: '6px',
                cursor: changed ? 'pointer' : 'default',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          )}
          <span style={{ color: '#6B7280', fontSize: '13px', marginLeft: 'auto' }}>
            Active: <strong style={{ fontFamily: 'monospace' }}>{provider}</strong>
          </span>
        </div>
      )}
    </div>
  );
};

export default TTSConfigPage;
