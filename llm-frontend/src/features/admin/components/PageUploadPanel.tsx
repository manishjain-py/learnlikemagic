/**
 * Page Upload Panel - Handles uploading and reviewing individual pages
 */

import React, { useState } from 'react';
import { uploadPage, approvePage, deletePage } from '../api/adminApi';
import { PageUploadResponse } from '../types';

interface PageUploadPanelProps {
  bookId: string;
  onPageProcessed: () => void;
}

const PageUploadPanel: React.FC<PageUploadPanelProps> = ({ bookId, onPageProcessed }) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<PageUploadResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setUploadData(null);
    setError(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    try {
      setLoading(true);
      setError(null);

      const result = await uploadPage(bookId, selectedFile);
      setUploadData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!uploadData) return;

    try {
      setLoading(true);
      await approvePage(bookId, uploadData.page_num);

      // Reset form
      setSelectedFile(null);
      setPreviewUrl(null);
      setUploadData(null);
      setError(null);

      // Notify parent
      onPageProcessed();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval failed');
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!uploadData) return;

    try {
      setLoading(true);
      await deletePage(bookId, uploadData.page_num);

      // Reset to allow re-upload
      setUploadData(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rejection failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px' }}>
        Upload Page
      </h3>

      {error && (
        <div style={{
          padding: '12px',
          backgroundColor: '#FEE2E2',
          color: '#991B1B',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '14px'
        }}>
          {error}
        </div>
      )}

      {!selectedFile && !uploadData && (
        <div>
          <label
            htmlFor="page-upload"
            style={{
              display: 'block',
              padding: '40px',
              border: '2px dashed #D1D5DB',
              borderRadius: '8px',
              textAlign: 'center',
              cursor: 'pointer',
              backgroundColor: '#F9FAFB',
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.currentTarget.style.backgroundColor = '#EBF5FF';
            }}
            onDragLeave={(e) => {
              e.currentTarget.style.backgroundColor = '#F9FAFB';
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.currentTarget.style.backgroundColor = '#F9FAFB';
              const file = e.dataTransfer.files[0];
              if (file && file.type.startsWith('image/')) {
                setSelectedFile(file);
                setPreviewUrl(URL.createObjectURL(file));
              }
            }}
          >
            <div style={{ fontSize: '48px', marginBottom: '8px' }}>📄</div>
            <div style={{ fontSize: '14px', color: '#6B7280', marginBottom: '8px' }}>
              Click to upload or drag and drop
            </div>
            <div style={{ fontSize: '12px', color: '#9CA3AF' }}>
              PNG, JPG, TIFF, WebP (max 10MB)
            </div>
            <input
              id="page-upload"
              type="file"
              accept="image/*"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      )}

      {selectedFile && !uploadData && (
        <div>
          <div style={{ marginBottom: '16px' }}>
            <img
              src={previewUrl!}
              alt="Preview"
              style={{
                maxWidth: '100%',
                maxHeight: '400px',
                borderRadius: '6px',
                border: '1px solid #E5E7EB',
              }}
            />
          </div>
          <div style={{ fontSize: '14px', color: '#6B7280', marginBottom: '16px' }}>
            {selectedFile.name} ({(selectedFile.size / 1024).toFixed(0)} KB)
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={handleUpload}
              disabled={loading}
              style={{
                padding: '10px 20px',
                backgroundColor: loading ? '#9CA3AF' : '#3B82F6',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: loading ? 'not-allowed' : 'pointer',
                fontWeight: '500',
              }}
            >
              {loading ? 'Processing...' : 'Upload & Process OCR'}
            </button>
            <button
              onClick={() => {
                setSelectedFile(null);
                setPreviewUrl(null);
              }}
              disabled={loading}
              style={{
                padding: '10px 20px',
                backgroundColor: 'white',
                color: '#374151',
                border: '1px solid #D1D5DB',
                borderRadius: '6px',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {uploadData && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            {/* Image */}
            <div>
              <div style={{ fontSize: '12px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>
                Original Image
              </div>
              <img
                src={uploadData.image_url}
                alt={`Page ${uploadData.page_num}`}
                style={{
                  width: '100%',
                  borderRadius: '6px',
                  border: '1px solid #E5E7EB',
                }}
              />
            </div>

            {/* OCR Text */}
            <div>
              <div style={{ fontSize: '12px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>
                Extracted Text
              </div>
              <div
                style={{
                  padding: '12px',
                  backgroundColor: '#F9FAFB',
                  borderRadius: '6px',
                  border: '1px solid #E5E7EB',
                  fontSize: '13px',
                  lineHeight: '1.6',
                  maxHeight: '400px',
                  overflowY: 'auto',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {uploadData.ocr_text}
              </div>
            </div>
          </div>

          <div style={{ padding: '12px', backgroundColor: '#EBF5FF', borderRadius: '6px', marginBottom: '16px' }}>
            <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '4px' }}>
              Page {uploadData.page_num} - Review Required
            </div>
            <div style={{ fontSize: '13px', color: '#6B7280' }}>
              Please review the extracted text. Approve if correct, or reject to re-upload.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={handleApprove}
              disabled={loading}
              style={{
                padding: '10px 20px',
                backgroundColor: loading ? '#9CA3AF' : '#10B981',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: loading ? 'not-allowed' : 'pointer',
                fontWeight: '500',
              }}
            >
              {loading ? 'Approving...' : '✓ Approve Page'}
            </button>
            <button
              onClick={handleReject}
              disabled={loading}
              style={{
                padding: '10px 20px',
                backgroundColor: loading ? '#F3F4F6' : 'white',
                color: '#DC2626',
                border: '1px solid #DC2626',
                borderRadius: '6px',
                cursor: loading ? 'not-allowed' : 'pointer',
                fontWeight: '500',
              }}
            >
              {loading ? 'Rejecting...' : '✗ Reject & Re-upload'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default PageUploadPanel;
