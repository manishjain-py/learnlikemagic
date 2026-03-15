/**
 * Feature Flags Admin Page — toggle runtime feature flags on/off.
 */

import React, { useState, useEffect } from 'react';
import { getFeatureFlags, updateFeatureFlag } from '../api/adminApi';
import { FeatureFlag } from '../types';

const FeatureFlagsPage: React.FC = () => {
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadFlags();
  }, []);

  const loadFlags = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getFeatureFlags();
      setFlags(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load feature flags');
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (flag: FeatureFlag) => {
    setSaving(prev => ({ ...prev, [flag.flag_name]: true }));
    try {
      const updated = await updateFeatureFlag(flag.flag_name, !flag.enabled);
      setFlags(prev => prev.map(f => f.flag_name === flag.flag_name ? updated : f));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update flag');
    } finally {
      setSaving(prev => ({ ...prev, [flag.flag_name]: false }));
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '900px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          Feature Flags
        </h1>
        <p style={{ color: '#6B7280' }}>
          Toggle features on or off. Changes take effect immediately for new sessions.
        </p>
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
      ) : flags.length === 0 ? (
        <p style={{ color: '#6B7280' }}>No feature flags configured. Run migrations to seed defaults.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {flags.map((flag) => {
            const isSaving = saving[flag.flag_name];
            return (
              <div
                key={flag.flag_name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '20px 24px',
                  backgroundColor: 'white',
                  border: '1px solid #E5E7EB',
                  borderRadius: '10px',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontFamily: 'monospace',
                    fontSize: '15px',
                    fontWeight: 600,
                    color: '#111827',
                    marginBottom: '4px',
                  }}>
                    {flag.flag_name}
                  </div>
                  <div style={{ fontSize: '13px', color: '#6B7280' }}>
                    {flag.description || 'No description'}
                  </div>
                  {flag.updated_at && (
                    <div style={{ fontSize: '11px', color: '#9CA3AF', marginTop: '4px' }}>
                      Updated {new Date(flag.updated_at).toLocaleString()}
                    </div>
                  )}
                </div>

                {/* Toggle switch */}
                <button
                  onClick={() => handleToggle(flag)}
                  disabled={isSaving}
                  style={{
                    position: 'relative',
                    width: '52px',
                    height: '28px',
                    borderRadius: '14px',
                    border: 'none',
                    cursor: isSaving ? 'wait' : 'pointer',
                    backgroundColor: flag.enabled ? '#4F46E5' : '#D1D5DB',
                    transition: 'background-color 0.2s',
                    flexShrink: 0,
                    marginLeft: '24px',
                    opacity: isSaving ? 0.6 : 1,
                  }}
                  title={flag.enabled ? 'Click to disable' : 'Click to enable'}
                >
                  <div style={{
                    position: 'absolute',
                    top: '2px',
                    left: flag.enabled ? '26px' : '2px',
                    width: '24px',
                    height: '24px',
                    borderRadius: '12px',
                    backgroundColor: 'white',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    transition: 'left 0.2s',
                  }} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default FeatureFlagsPage;
