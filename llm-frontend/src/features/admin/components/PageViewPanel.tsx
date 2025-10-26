/**
 * Page View Panel - View approved page with image and OCR text
 */

import React, { useState, useEffect } from 'react';
import { getPage, deletePage } from '../api/adminApi';
import { PageDetails } from '../types';

interface PageViewPanelProps {
  bookId: string;
  pageNum: number;
  onClose: () => void;
  onReplace: () => void;
  onPageDeleted: () => void;
}

const PageViewPanel: React.FC<PageViewPanelProps> = ({
  bookId,
  pageNum,
  onClose,
  onReplace,
  onPageDeleted,
}) => {
  const [pageDetails, setPageDetails] = useState<PageDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  useEffect(() => {
    loadPageDetails();
  }, [bookId, pageNum]);

  const loadPageDetails = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getPage(bookId, pageNum);
      setPageDetails(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load page');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to delete page ${pageNum}? This will renumber all subsequent pages.`)) {
      return;
    }

    try {
      setDeleteLoading(true);
      await deletePage(bookId, pageNum);
      onPageDeleted();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete page');
    } finally {
      setDeleteLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
        <p>Loading page details...</p>
      </div>
    );
  }

  if (error || !pageDetails) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
        <p style={{ color: '#DC2626', marginBottom: '16px' }}>{error || 'Failed to load page'}</p>
        <button
          onClick={onClose}
          style={{
            padding: '8px 16px',
            backgroundColor: '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Back
        </button>
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: 'white', padding: '24px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '4px' }}>
            Page {pageNum}
          </h3>
          <div style={{ display: 'inline-block', padding: '4px 12px', backgroundColor: '#D1FAE5', color: '#065F46', borderRadius: '12px', fontSize: '12px', fontWeight: '500' }}>
            ✓ Approved
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            padding: '8px 16px',
            backgroundColor: 'white',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
          }}
        >
          ← Back
        </button>
      </div>

      {/* Side-by-side view */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
        {/* Image preview */}
        <div>
          <h4 style={{ fontSize: '14px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>
            Page Image
          </h4>
          <div style={{ border: '1px solid #E5E7EB', borderRadius: '6px', overflow: 'hidden', backgroundColor: '#F9FAFB' }}>
            <img
              src={pageDetails.image_url}
              alt={`Page ${pageNum}`}
              style={{ width: '100%', height: 'auto', display: 'block' }}
            />
          </div>
        </div>

        {/* OCR text */}
        <div>
          <h4 style={{ fontSize: '14px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>
            Extracted Text
          </h4>
          <div style={{ border: '1px solid #E5E7EB', borderRadius: '6px', padding: '16px', backgroundColor: '#F9FAFB', height: '400px', overflowY: 'auto' }}>
            <pre style={{ margin: 0, fontFamily: 'monospace', fontSize: '13px', lineHeight: '1.6', whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>
              {pageDetails.ocr_text}
            </pre>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
        <button
          onClick={handleDelete}
          disabled={deleteLoading}
          style={{
            padding: '10px 20px',
            backgroundColor: deleteLoading ? '#FCA5A5' : '#DC2626',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: deleteLoading ? 'not-allowed' : 'pointer',
            fontWeight: '500',
            fontSize: '14px',
          }}
        >
          {deleteLoading ? 'Deleting...' : 'Delete Page'}
        </button>
        <button
          onClick={onReplace}
          style={{
            padding: '10px 20px',
            backgroundColor: '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: '500',
            fontSize: '14px',
          }}
        >
          Replace Page
        </button>
      </div>
    </div>
  );
};

export default PageViewPanel;
