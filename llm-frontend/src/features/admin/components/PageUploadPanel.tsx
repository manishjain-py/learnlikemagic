/**
 * Page Upload Panel - Handles bulk and single page upload
 */

import React, { useState } from 'react';
import { uploadPage, approvePage, deletePage, bulkUploadPages } from '../api/adminApi';
import { useJobPolling } from '../hooks/useJobPolling';
import { PageUploadResponse, JobStatus, PageInfo } from '../types';

interface PageUploadPanelProps {
  bookId: string;
  onPageProcessed: () => void;
  pages?: PageInfo[];
}

const PageUploadPanel: React.FC<PageUploadPanelProps> = ({ bookId, onPageProcessed, pages }) => {
  const [mode, setMode] = useState<'bulk' | 'single'>('bulk');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<PageUploadResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Poll for OCR job progress
  const { job: ocrJob, isPolling: isOcrRunning, startPolling: startOcrPolling } = useJobPolling(bookId, 'ocr_batch');

  // ===== Bulk Upload Handlers =====

  const handleBulkFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles(files);
    setError(null);
  };

  const handleBulkDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.currentTarget.style.backgroundColor = '#F9FAFB';
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    if (files.length > 0) {
      setSelectedFiles(files);
      setError(null);
    }
  };

  const handleBulkUpload = async () => {
    if (selectedFiles.length === 0) return;

    try {
      setLoading(true);
      setError(null);
      const result = await bulkUploadPages(bookId, selectedFiles);
      setSelectedFiles([]);

      // Start polling for OCR progress
      if (result.job_id) {
        startOcrPolling(result.job_id);
      }
      onPageProcessed();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk upload failed');
    } finally {
      setLoading(false);
    }
  };

  // ===== Single Upload Handlers =====

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
      setSelectedFile(null);
      setPreviewUrl(null);
      setUploadData(null);
      setError(null);
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
      setUploadData(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rejection failed');
    } finally {
      setLoading(false);
    }
  };

  // Reload when OCR completes
  React.useEffect(() => {
    if (ocrJob?.status === 'completed') {
      onPageProcessed();
    }
  }, [ocrJob?.status]);

  return (
    <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h3 style={{ fontSize: '18px', fontWeight: '600', margin: 0 }}>
          Upload Pages
        </h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setMode('bulk')}
            style={{
              padding: '6px 12px', fontSize: '13px', borderRadius: '6px', cursor: 'pointer',
              backgroundColor: mode === 'bulk' ? '#3B82F6' : 'white',
              color: mode === 'bulk' ? 'white' : '#6B7280',
              border: mode === 'bulk' ? 'none' : '1px solid #D1D5DB',
            }}
          >
            Bulk Upload
          </button>
          <button
            onClick={() => setMode('single')}
            style={{
              padding: '6px 12px', fontSize: '13px', borderRadius: '6px', cursor: 'pointer',
              backgroundColor: mode === 'single' ? '#3B82F6' : 'white',
              color: mode === 'single' ? 'white' : '#6B7280',
              border: mode === 'single' ? 'none' : '1px solid #D1D5DB',
            }}
          >
            Single Page
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '12px', backgroundColor: '#FEE2E2', color: '#991B1B',
          borderRadius: '6px', marginBottom: '16px', fontSize: '14px'
        }}>
          {error}
        </div>
      )}

      {/* OCR Progress Bar */}
      {ocrJob && (ocrJob.status === 'running' || ocrJob.status === 'pending') && (
        <div style={{ padding: '16px', backgroundColor: '#EFF6FF', borderRadius: '8px', border: '1px solid #BFDBFE', marginBottom: '16px' }}>
          <div style={{ fontSize: '14px', fontWeight: '600', color: '#1E40AF', marginBottom: '8px' }}>
            Processing OCR
          </div>
          <div style={{ height: '8px', backgroundColor: '#DBEAFE', borderRadius: '4px', overflow: 'hidden', marginBottom: '8px' }}>
            <div style={{
              height: '100%',
              width: `${Math.round(((ocrJob.completed_items || 0) / (ocrJob.total_items || 1)) * 100)}%`,
              backgroundColor: '#3B82F6', borderRadius: '4px', transition: 'width 0.3s',
            }} />
          </div>
          <div style={{ fontSize: '13px', color: '#1E40AF' }}>
            {ocrJob.completed_items}/{ocrJob.total_items} pages ({Math.round(((ocrJob.completed_items || 0) / (ocrJob.total_items || 1)) * 100)}%)
          </div>
          {ocrJob.current_item && (
            <div style={{ fontSize: '12px', color: '#6B7280', marginTop: '4px' }}>
              Processing page {ocrJob.current_item}
            </div>
          )}
          {ocrJob.failed_items > 0 && (
            <div style={{ fontSize: '12px', color: '#DC2626', marginTop: '4px' }}>
              {ocrJob.failed_items} page(s) had OCR errors
            </div>
          )}
          <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '8px', fontStyle: 'italic' }}>
            You can leave this page - OCR continues in the background.
          </div>
        </div>
      )}

      {/* Bulk Upload Mode */}
      {mode === 'bulk' && !isOcrRunning && (
        <>
          {selectedFiles.length === 0 ? (
            <label
              htmlFor="bulk-upload"
              style={{
                display: 'block', padding: '40px', border: '2px dashed #D1D5DB',
                borderRadius: '8px', textAlign: 'center', cursor: 'pointer', backgroundColor: '#F9FAFB',
              }}
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.backgroundColor = '#EBF5FF'; }}
              onDragLeave={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; }}
              onDrop={handleBulkDrop}
            >
              <div style={{ fontSize: '48px', marginBottom: '8px' }}>📚</div>
              <div style={{ fontSize: '14px', color: '#6B7280', marginBottom: '8px' }}>
                Drop multiple images here or click to select
              </div>
              <div style={{ fontSize: '12px', color: '#9CA3AF' }}>
                PNG, JPG, TIFF, WebP (max 200 files, 20MB each)
              </div>
              <input
                id="bulk-upload"
                type="file"
                accept="image/*"
                multiple
                onChange={handleBulkFileSelect}
                style={{ display: 'none' }}
              />
            </label>
          ) : (
            <div>
              <div style={{ padding: '16px', backgroundColor: '#F0FDF4', borderRadius: '8px', marginBottom: '16px', border: '1px solid #BBF7D0' }}>
                <div style={{ fontSize: '14px', fontWeight: '600', color: '#166534', marginBottom: '4px' }}>
                  Selected: {selectedFiles.length} images
                </div>
                <div style={{ fontSize: '12px', color: '#6B7280' }}>
                  {selectedFiles.slice(0, 5).map(f => f.name).join(', ')}
                  {selectedFiles.length > 5 && `, ... and ${selectedFiles.length - 5} more`}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={handleBulkUpload}
                  disabled={loading}
                  style={{
                    padding: '10px 20px', backgroundColor: loading ? '#9CA3AF' : '#3B82F6',
                    color: 'white', border: 'none', borderRadius: '6px',
                    cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '500',
                  }}
                >
                  {loading ? 'Uploading...' : `Upload All & Start OCR (${selectedFiles.length} files)`}
                </button>
                <button
                  onClick={() => setSelectedFiles([])}
                  disabled={loading}
                  style={{
                    padding: '10px 20px', backgroundColor: 'white', color: '#374151',
                    border: '1px solid #D1D5DB', borderRadius: '6px',
                    cursor: loading ? 'not-allowed' : 'pointer',
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Per-page OCR status list (shown after bulk upload completes or when pages have ocr_status) */}
      {pages && pages.some(p => p.ocr_status && p.ocr_status !== 'completed') && (
        <div style={{ marginTop: '16px', maxHeight: '300px', overflowY: 'auto' }}>
          <div style={{ fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>
            OCR Status per Page
          </div>
          {pages
            .filter(p => p.ocr_status)
            .map(page => (
              <div key={page.page_num} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 12px', borderBottom: '1px solid #F3F4F6', fontSize: '13px',
              }}>
                <span>Page {page.page_num}</span>
                <span>
                  {page.ocr_status === 'completed' && <span style={{ color: '#10B981' }}>OCR Complete</span>}
                  {page.ocr_status === 'processing' && <span style={{ color: '#F59E0B' }}>Processing...</span>}
                  {page.ocr_status === 'failed' && <span style={{ color: '#EF4444' }}>Failed</span>}
                  {page.ocr_status === 'pending' && <span style={{ color: '#9CA3AF' }}>Pending</span>}
                </span>
              </div>
            ))}
        </div>
      )}

      {/* Single Upload Mode */}
      {mode === 'single' && (
        <>
          {!selectedFile && !uploadData && (
            <label
              htmlFor="page-upload"
              style={{
                display: 'block', padding: '40px', border: '2px dashed #D1D5DB',
                borderRadius: '8px', textAlign: 'center', cursor: 'pointer', backgroundColor: '#F9FAFB',
              }}
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.backgroundColor = '#EBF5FF'; }}
              onDragLeave={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; }}
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
                PNG, JPG, TIFF, WebP (max 20MB)
              </div>
              <input
                id="page-upload"
                type="file"
                accept="image/*"
                onChange={handleFileSelect}
                style={{ display: 'none' }}
              />
            </label>
          )}

          {selectedFile && !uploadData && (
            <div>
              <div style={{ marginBottom: '16px' }}>
                <img src={previewUrl!} alt="Preview" style={{
                  maxWidth: '100%', maxHeight: '400px', borderRadius: '6px', border: '1px solid #E5E7EB',
                }} />
              </div>
              <div style={{ fontSize: '14px', color: '#6B7280', marginBottom: '16px' }}>
                {selectedFile.name} ({(selectedFile.size / 1024).toFixed(0)} KB)
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={handleUpload}
                  disabled={loading}
                  style={{
                    padding: '10px 20px', backgroundColor: loading ? '#9CA3AF' : '#3B82F6',
                    color: 'white', border: 'none', borderRadius: '6px',
                    cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '500',
                  }}
                >
                  {loading ? 'Processing...' : 'Upload & Process OCR'}
                </button>
                <button
                  onClick={() => { setSelectedFile(null); setPreviewUrl(null); }}
                  disabled={loading}
                  style={{
                    padding: '10px 20px', backgroundColor: 'white', color: '#374151',
                    border: '1px solid #D1D5DB', borderRadius: '6px',
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
                <div>
                  <div style={{ fontSize: '12px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>Original Image</div>
                  <img src={uploadData.image_url} alt={`Page ${uploadData.page_num}`} style={{
                    width: '100%', borderRadius: '6px', border: '1px solid #E5E7EB',
                  }} />
                </div>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: '500', marginBottom: '8px', color: '#6B7280' }}>Extracted Text</div>
                  <div style={{
                    padding: '12px', backgroundColor: '#F9FAFB', borderRadius: '6px', border: '1px solid #E5E7EB',
                    fontSize: '13px', lineHeight: '1.6', maxHeight: '400px', overflowY: 'auto', whiteSpace: 'pre-wrap',
                  }}>
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
                <button onClick={handleApprove} disabled={loading} style={{
                  padding: '10px 20px', backgroundColor: loading ? '#9CA3AF' : '#10B981',
                  color: 'white', border: 'none', borderRadius: '6px',
                  cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '500',
                }}>
                  {loading ? 'Approving...' : 'Approve Page'}
                </button>
                <button onClick={handleReject} disabled={loading} style={{
                  padding: '10px 20px', backgroundColor: loading ? '#F3F4F6' : 'white',
                  color: '#DC2626', border: '1px solid #DC2626', borderRadius: '6px',
                  cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '500',
                }}>
                  {loading ? 'Rejecting...' : 'Reject & Re-upload'}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default PageUploadPanel;
