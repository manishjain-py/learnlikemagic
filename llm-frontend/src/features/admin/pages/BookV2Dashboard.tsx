import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listBooksV2, BookV2Response } from '../api/adminApiV2';

const STATUS_COLORS: Record<string, string> = {
  toc_defined: '#6B7280',
  upload_in_progress: '#F59E0B',
  upload_complete: '#3B82F6',
  topic_extraction: '#8B5CF6',
  chapter_finalizing: '#8B5CF6',
  chapter_completed: '#10B981',
  failed: '#EF4444',
};

const BookV2Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [books, setBooks] = useState<BookV2Response[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadBooks();
  }, []);

  const loadBooks = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await listBooksV2();
      setBooks(response.books);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load books');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '24px' }}>Book Ingestion V2</h1>
          <p style={{ color: '#6B7280', margin: '4px 0 0' }}>Chapter-first, topic-only pipeline</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={() => navigate('/admin/books-v2/new')}
            style={{
              backgroundColor: '#3B82F6', color: 'white', border: 'none',
              padding: '10px 20px', borderRadius: '8px', cursor: 'pointer',
              fontWeight: 600, fontSize: '14px',
            }}
          >
            + Create New Book
          </button>
          <button
            onClick={loadBooks}
            style={{
              backgroundColor: '#F3F4F6', border: '1px solid #D1D5DB',
              padding: '10px 16px', borderRadius: '8px', cursor: 'pointer',
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {loading && <div style={{ padding: '40px', textAlign: 'center', color: '#6B7280' }}>Loading books...</div>}

      {error && (
        <div style={{ backgroundColor: '#FEE2E2', color: '#991B1B', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {!loading && !error && books.length === 0 && (
        <div style={{ padding: '60px', textAlign: 'center', backgroundColor: '#F9FAFB', borderRadius: '12px', border: '2px dashed #D1D5DB' }}>
          <p style={{ fontSize: '18px', color: '#6B7280' }}>No V2 books yet</p>
          <button
            onClick={() => navigate('/admin/books-v2/new')}
            style={{
              backgroundColor: '#3B82F6', color: 'white', border: 'none',
              padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', marginTop: '12px',
            }}
          >
            Create your first book
          </button>
        </div>
      )}

      {!loading && !error && books.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '20px' }}>
          {books.map((book) => (
            <div
              key={book.id}
              onClick={() => navigate(`/admin/books-v2/${book.id}`)}
              style={{
                backgroundColor: 'white', border: '1px solid #E5E7EB', borderRadius: '12px',
                padding: '20px', cursor: 'pointer', transition: 'box-shadow 0.2s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.boxShadow = '0 4px 6px rgba(0,0,0,0.1)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'none'; }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '8px' }}>
                <h3 style={{ margin: 0, fontSize: '16px' }}>{book.title}</h3>
                <span style={{
                  backgroundColor: '#DBEAFE', color: '#1D4ED8',
                  padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 600,
                }}>
                  V2
                </span>
              </div>
              <p style={{ color: '#6B7280', margin: '4px 0', fontSize: '14px' }}>{book.author || 'Unknown Author'}</p>
              <div style={{ color: '#9CA3AF', fontSize: '13px', marginTop: '8px' }}>
                {book.board} &bull; Grade {book.grade} &bull; {book.subject}
              </div>
              <div style={{ marginTop: '12px', fontSize: '13px', color: '#6B7280' }}>
                {book.chapter_count} chapters
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default BookV2Dashboard;
