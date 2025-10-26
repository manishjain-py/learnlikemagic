/**
 * Book Detail Page - Main page for managing a specific book
 */

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getBook, updateBookStatus, deletePage } from '../api/adminApi';
import { BookDetail as BookDetailType } from '../types';
import BookStatusBadge from '../components/BookStatusBadge';
import PageUploadPanel from '../components/PageUploadPanel';
import PagesSidebar from '../components/PagesSidebar';
import PageViewPanel from '../components/PageViewPanel';

const BookDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [showUploadAfterReplace, setShowUploadAfterReplace] = useState(false);

  useEffect(() => {
    if (id) {
      loadBook();
    }
  }, [id]);

  const loadBook = async () => {
    if (!id) return;

    try {
      setLoading(true);
      setError(null);
      const data = await getBook(id);
      setBook(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load book');
    } finally {
      setLoading(false);
    }
  };

  const handleMarkComplete = async () => {
    if (!id || !book) return;

    try {
      setActionLoading(true);
      await updateBookStatus(id, 'pages_complete');
      await loadBook();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to update status');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePageClick = (pageNum: number) => {
    setSelectedPage(pageNum);
    setShowUploadAfterReplace(false);
  };

  const handleClosePageView = () => {
    setSelectedPage(null);
    setShowUploadAfterReplace(false);
  };

  const handleReplacePage = async () => {
    if (!id || !selectedPage) return;

    if (!confirm(`Delete page ${selectedPage} and upload a replacement? The new page will be added at the end.`)) {
      return;
    }

    try {
      setActionLoading(true);
      await deletePage(id, selectedPage);
      await loadBook();
      setSelectedPage(null);
      setShowUploadAfterReplace(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete page');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePageDeleted = async () => {
    await loadBook();
    setSelectedPage(null);
    setShowUploadAfterReplace(false);
  };

  const handlePageProcessed = async () => {
    await loadBook();
    setShowUploadAfterReplace(false);
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <p>Loading book...</p>
      </div>
    );
  }

  if (error || !book) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <p style={{ color: '#DC2626' }}>{error || 'Book not found'}</p>
        <button
          onClick={() => navigate('/admin/books')}
          style={{
            marginTop: '20px',
            padding: '10px 20px',
            backgroundColor: '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Back to Books
        </button>
      </div>
    );
  }

  const canUploadPages = book.status === 'draft' || book.status === 'uploading_pages';
  const canMarkComplete = book.status === 'uploading_pages' && book.pages.some(p => p.status === 'approved');

  return (
    <div style={{ padding: '20px', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <button
          onClick={() => navigate('/admin/books')}
          style={{
            padding: '8px 16px',
            backgroundColor: 'white',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
            marginBottom: '20px',
          }}
        >
          ← Back to Books
        </button>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
          <div>
            <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '8px' }}>
              {book.title}
            </h1>
            <p style={{ color: '#6B7280', marginBottom: '12px' }}>
              {book.author} • {book.board} • Grade {book.grade} • {book.subject}
            </p>
            <BookStatusBadge status={book.status} />
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            {canMarkComplete && (
              <button
                onClick={handleMarkComplete}
                disabled={actionLoading}
                style={{
                  padding: '10px 20px',
                  backgroundColor: actionLoading ? '#9CA3AF' : '#10B981',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: actionLoading ? 'not-allowed' : 'pointer',
                  fontWeight: '500',
                }}
              >
                {actionLoading ? 'Updating...' : 'Mark Book Complete'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '30px' }}>
        <div style={{ padding: '16px', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: '24px', fontWeight: '600', color: '#3B82F6' }}>
            {book.pages.length}
          </div>
          <div style={{ fontSize: '14px', color: '#6B7280' }}>Total Pages</div>
        </div>
        <div style={{ padding: '16px', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: '24px', fontWeight: '600', color: '#10B981' }}>
            {book.pages.filter(p => p.status === 'approved').length}
          </div>
          <div style={{ fontSize: '14px', color: '#6B7280' }}>Approved Pages</div>
        </div>
        <div style={{ padding: '16px', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
          <div style={{ fontSize: '24px', fontWeight: '600', color: '#F59E0B' }}>
            {book.pages.filter(p => p.status === 'pending_review').length}
          </div>
          <div style={{ fontSize: '14px', color: '#6B7280' }}>Pending Review</div>
        </div>
      </div>

      {/* Main Content - Two Column Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '20px' }}>
        {/* Left: Dynamic Panel - Upload or View */}
        <div>
          {selectedPage !== null && !showUploadAfterReplace ? (
            // Show page view when a page is selected
            <PageViewPanel
              bookId={book.id}
              pageNum={selectedPage}
              onClose={handleClosePageView}
              onReplace={handleReplacePage}
              onPageDeleted={handlePageDeleted}
            />
          ) : (canUploadPages || showUploadAfterReplace) ? (
            // Show upload panel when allowed or after replace
            <div>
              {showUploadAfterReplace && (
                <div style={{
                  padding: '12px',
                  backgroundColor: '#DBEAFE',
                  color: '#1E40AF',
                  borderRadius: '6px',
                  marginBottom: '16px',
                  fontSize: '14px'
                }}>
                  Upload a replacement page below. The new page will be added at the end of the book.
                </div>
              )}
              <PageUploadPanel
                bookId={book.id}
                onPageProcessed={handlePageProcessed}
              />
            </div>
          ) : (
            // Show disabled message
            <div style={{
              padding: '40px',
              backgroundColor: '#F9FAFB',
              borderRadius: '8px',
              border: '1px solid #E5E7EB',
              textAlign: 'center',
            }}>
              <p style={{ color: '#6B7280', marginBottom: '8px' }}>
                Page upload is disabled for books in "{book.status}" status
              </p>
              <p style={{ fontSize: '14px', color: '#9CA3AF' }}>
                Book must be in "draft" or "uploading_pages" status to upload pages
              </p>
            </div>
          )}
        </div>

        {/* Right: Approved Pages Sidebar */}
        <div>
          <PagesSidebar
            pages={book.pages}
            selectedPage={selectedPage}
            onSelectPage={handlePageClick}
          />
        </div>
      </div>

      {/* Guideline Section (placeholder for Phase 6) */}
      {book.status === 'pages_complete' && (
        <div style={{ marginTop: '30px', padding: '20px', backgroundColor: '#FEF3C7', borderRadius: '8px', border: '1px solid #FDE68A' }}>
          <h3 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '8px' }}>
            Ready for Guideline Generation
          </h3>
          <p style={{ fontSize: '14px', color: '#92400E', marginBottom: '12px' }}>
            All pages have been uploaded and approved. You can now generate teaching guidelines.
          </p>
          <button
            style={{
              padding: '10px 20px',
              backgroundColor: '#F59E0B',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'not-allowed',
              opacity: 0.6,
            }}
            disabled
            title="Guideline generation will be available in Phase 6"
          >
            Generate Guidelines (Coming Soon)
          </button>
        </div>
      )}
    </div>
  );
};

export default BookDetail;
