/**
 * SectionCard — Collapsible wrapper for each enrichment section.
 */

import React from 'react';

interface SectionCardProps {
  title: string;
  helper: string;
  isFilled: boolean;
  isOpen: boolean;
  onToggle: () => void;
  onSave: () => void;
  saving: boolean;
  children: React.ReactNode;
}

export default function SectionCard({ title, helper, isFilled, isOpen, onToggle, onSave, saving, children }: SectionCardProps) {
  return (
    <div className={`enrichment-section ${isOpen ? 'enrichment-section-open' : ''}`}>
      <button type="button" className="enrichment-section-header" onClick={onToggle}>
        <div className="enrichment-section-title">
          <span className={`enrichment-section-dot ${isFilled ? 'enrichment-section-dot-filled' : ''}`} />
          <span>{title}</span>
        </div>
        <span className="enrichment-section-arrow">{isOpen ? '\u25B2' : '\u25BC'}</span>
      </button>
      {isOpen && (
        <div className="enrichment-section-body">
          <p className="enrichment-section-helper">{helper}</p>
          {children}
          <div className="enrichment-section-save">
            <button
              type="button"
              className="auth-btn auth-btn-primary enrichment-save-btn"
              onClick={onSave}
              disabled={saving}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
