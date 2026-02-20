/**
 * LLM Config Admin Page — single source of truth for component→provider→model mapping.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getLLMConfigs, updateLLMConfig, getLLMConfigOptions } from '../api/adminApi';
import { LLMConfig, LLMConfigOptions } from '../types';

const LLMConfigPage: React.FC = () => {
  const navigate = useNavigate();
  const [configs, setConfigs] = useState<LLMConfig[]>([]);
  const [options, setOptions] = useState<LLMConfigOptions>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track edits per row: componentKey → {provider, model_id}
  const [edits, setEdits] = useState<Record<string, { provider: string; model_id: string }>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveSuccess, setSaveSuccess] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [configData, optionData] = await Promise.all([
        getLLMConfigs(),
        getLLMConfigOptions(),
      ]);
      setConfigs(configData);
      setOptions(optionData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load LLM config');
    } finally {
      setLoading(false);
    }
  };

  const getEditValue = (config: LLMConfig) => {
    return edits[config.component_key] || { provider: config.provider, model_id: config.model_id };
  };

  const hasChanges = (config: LLMConfig) => {
    const edit = edits[config.component_key];
    if (!edit) return false;
    return edit.provider !== config.provider || edit.model_id !== config.model_id;
  };

  const handleProviderChange = (config: LLMConfig, newProvider: string) => {
    const models = options[newProvider] || [];
    setEdits(prev => ({
      ...prev,
      [config.component_key]: {
        provider: newProvider,
        model_id: models[0] || '',
      },
    }));
  };

  const handleModelChange = (config: LLMConfig, newModel: string) => {
    const current = getEditValue(config);
    setEdits(prev => ({
      ...prev,
      [config.component_key]: { ...current, model_id: newModel },
    }));
  };

  const handleSave = async (config: LLMConfig) => {
    const edit = getEditValue(config);
    setSaving(prev => ({ ...prev, [config.component_key]: true }));
    setSaveSuccess(prev => ({ ...prev, [config.component_key]: false }));
    try {
      await updateLLMConfig(config.component_key, edit.provider, edit.model_id);
      // Clear edit state and reload
      setEdits(prev => {
        const next = { ...prev };
        delete next[config.component_key];
        return next;
      });
      setSaveSuccess(prev => ({ ...prev, [config.component_key]: true }));
      setTimeout(() => setSaveSuccess(prev => ({ ...prev, [config.component_key]: false })), 2000);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(prev => ({ ...prev, [config.component_key]: false }));
    }
  };

  const providers = Object.keys(options);

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          LLM Model Configuration
        </h1>
        <p style={{ color: '#6B7280' }}>
          Configure which LLM provider and model each component uses. Changes take effect immediately for new sessions.
        </p>
      </div>

      {/* Navigation */}
      <div style={{ marginBottom: '20px', display: 'flex', gap: '10px' }}>
        <button
          onClick={() => navigate('/admin/books')}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Books
        </button>
        <button
          onClick={() => navigate('/admin/guidelines')}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Guidelines Review
        </button>
        <button
          onClick={() => navigate('/admin/evaluation')}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Evaluation
        </button>
        <button
          disabled
          style={{
            padding: '10px 20px',
            backgroundColor: '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            fontWeight: '500',
          }}
        >
          LLM Config
        </button>
      </div>

      {/* Error */}
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

      {/* Loading */}
      {loading ? (
        <p style={{ color: '#6B7280' }}>Loading...</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', backgroundColor: 'white', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
            <thead>
              <tr style={{ backgroundColor: '#F9FAFB', borderBottom: '1px solid #E5E7EB' }}>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: '600', fontSize: '14px', color: '#374151' }}>Component</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: '600', fontSize: '14px', color: '#374151' }}>Description</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: '600', fontSize: '14px', color: '#374151' }}>Provider</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: '600', fontSize: '14px', color: '#374151' }}>Model</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: '600', fontSize: '14px', color: '#374151' }}>Updated</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: '600', fontSize: '14px', color: '#374151' }}></th>
              </tr>
            </thead>
            <tbody>
              {configs.map((config) => {
                const edit = getEditValue(config);
                const changed = hasChanges(config);
                const isSaving = saving[config.component_key];
                const saved = saveSuccess[config.component_key];

                return (
                  <tr key={config.component_key} style={{ borderBottom: '1px solid #E5E7EB' }}>
                    <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontSize: '13px', fontWeight: '600' }}>
                      {config.component_key}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '13px', color: '#6B7280', maxWidth: '250px' }}>
                      {config.description || '—'}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <select
                        value={edit.provider}
                        onChange={(e) => handleProviderChange(config, e.target.value)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: '4px',
                          border: '1px solid #D1D5DB',
                          fontSize: '13px',
                          backgroundColor: changed ? '#FEF9C3' : 'white',
                        }}
                      >
                        {providers.map(p => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <select
                        value={edit.model_id}
                        onChange={(e) => handleModelChange(config, e.target.value)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: '4px',
                          border: '1px solid #D1D5DB',
                          fontSize: '13px',
                          backgroundColor: changed ? '#FEF9C3' : 'white',
                        }}
                      >
                        {(options[edit.provider] || []).map(m => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '12px', color: '#9CA3AF' }}>
                      {config.updated_at
                        ? new Date(config.updated_at).toLocaleString()
                        : '—'}
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      {saved ? (
                        <span style={{ color: '#059669', fontSize: '13px', fontWeight: '500' }}>Saved</span>
                      ) : (
                        <button
                          onClick={() => handleSave(config)}
                          disabled={!changed || isSaving}
                          style={{
                            padding: '6px 16px',
                            backgroundColor: changed ? '#3B82F6' : '#E5E7EB',
                            color: changed ? 'white' : '#9CA3AF',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: changed ? 'pointer' : 'default',
                            fontSize: '13px',
                            fontWeight: '500',
                          }}
                        >
                          {isSaving ? 'Saving...' : 'Save'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default LLMConfigPage;
