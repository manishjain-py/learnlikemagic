/**
 * Book Detail Page - Main page for managing a specific book
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getBook, deletePage, deleteBook } from '../api/adminApi';
import { BookDetail as BookDetailType } from '../types';
import { getDisplayStatus } from '../utils/bookStatus';
import BookStatusBadge from '../components/BookStatusBadge';
import PageUploadPanel from '../components/PageUploadPanel';
import PagesSidebar from '../components/PagesSidebar';
import PageViewPanel from '../components/PageViewPanel';
import { GuidelinesPanel } from '../components/GuidelinesPanel';

const BookDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [showUploadAfterReplace, setShowUploadAfterReplace] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [processedPages, setProcessedPages] = useState<Set<number>>(new Set());

  const handleProcessedPagesChange = useCallback((pages: Set<number>) => {
    setProcessedPages(pages);
  }, []);

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
      await deletePage(id, selectedPage);
      await loadBook();
      setSelectedPage(null);
      setShowUploadAfterReplace(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete page');
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

  const handleDeleteBook = async () => {
    if (!id || !book) return;

    const confirmMessage = `Are you sure you want to delete "${book.title}"?\n\nThis will permanently delete:\n- All ${book.pages.length} pages\n- All guidelines\n- All S3 files\n\nThis action cannot be undone.`;

    if (!confirm(confirmMessage)) {
      return;
    }

    try {
      setDeleting(true);
      await deleteBook(id);
      navigate('/admin/books');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete book');
      setDeleting(false);
    }
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

  const displayStatus = getDisplayStatus(book);

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
            <BookStatusBadge status={displayStatus} />
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={handleDeleteBook}
              disabled={deleting}
              style={{
                padding: '8px 16px',
                backgroundColor: deleting ? '#FCA5A5' : '#EF4444',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: deleting ? 'not-allowed' : 'pointer',
                fontWeight: '500',
              }}
            >
              {deleting ? 'Deleting...' : 'Delete Book'}
            </button>
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
              onApproved={loadBook}
            />
          ) : (
            // Always show upload panel
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
          )}
        </div>

        {/* Right: Approved Pages Sidebar */}
        <div>
          <PagesSidebar
            pages={book.pages}
            selectedPage={selectedPage}
            onSelectPage={handlePageClick}
            processedPages={processedPages}
          />
        </div>
      </div>

      {/* Guideline Section (Phase 6) */}
      {/* Only show guidelines when all pages are approved */}
      {book.pages.length > 0 && book.pages.every(p => p.status === 'approved') ? (
        <div style={{ marginTop: '30px' }}>
          <GuidelinesPanel
            bookId={book.id}
            totalPages={book.pages.length}
            onProcessedPagesChange={handleProcessedPagesChange}
          />
        </div>
      ) : book.pages.length > 0 && (
        <div style={{ marginTop: '30px', padding: '20px', backgroundColor: '#FEF3C7', borderRadius: '8px', border: '1px solid #FDE68A' }}>
          <div style={{ fontSize: '16px', fontWeight: '600', color: '#92400E', marginBottom: '4px' }}>
            Teaching Guidelines
          </div>
          <div style={{ fontSize: '14px', color: '#92400E' }}>
            Approve all pages before generating guidelines. {book.pages.filter(p => p.status === 'pending_review').length} page(s) still pending review.
          </div>
        </div>
      )}
    </div>
  );
};

export default BookDetail;
