/**
 * Books Dashboard - Main admin page for managing books
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listBooks } from '../api/adminApi';
import { Book } from '../types';
import { getDisplayStatus } from '../utils/bookStatus';
import BookStatusBadge from '../components/BookStatusBadge';

const BooksDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadBooks();
  }, []);

  const loadBooks = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await listBooks();
      setBooks(response.books);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load books');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          Book Ingestion Admin
        </h1>
        <p style={{ color: '#6B7280' }}>
          Manage textbooks and curriculum guidelines
        </p>
      </div>

      {/* Actions */}
      <div style={{ marginBottom: '20px', display: 'flex', gap: '10px' }}>
        <button
          onClick={() => navigate('/admin/books/new')}
          style={{
            padding: '10px 20px',
            backgroundColor: '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: '500',
          }}
        >
          + Create New Book
        </button>
        <button
          onClick={loadBooks}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Refresh
        </button>
      </div>

      {/* Loading State */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          <p>Loading books...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div
          style={{
            padding: '15px',
            backgroundColor: '#FEE2E2',
            color: '#991B1B',
            borderRadius: '6px',
            marginBottom: '20px',
          }}
        >
          {error}
        </div>
      )}

      {/* Books Grid */}
      {!loading && !error && (
        <div>
          {books.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '60px 20px',
                backgroundColor: '#F9FAFB',
                borderRadius: '8px',
                border: '2px dashed #D1D5DB',
              }}
            >
              <p style={{ fontSize: '18px', color: '#6B7280', marginBottom: '10px' }}>
                No books yet
              </p>
              <p style={{ color: '#9CA3AF', marginBottom: '20px' }}>
                Create your first book to get started
              </p>
              <button
                onClick={() => navigate('/admin/books/new')}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#3B82F6',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                }}
              >
                Create Book
              </button>
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                gap: '20px',
              }}
            >
              {books.map((book) => (
                <div
                  key={book.id}
                  onClick={() => navigate(`/admin/books/${book.id}`)}
                  style={{
                    padding: '20px',
                    backgroundColor: 'white',
                    border: '1px solid #E5E7EB',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.boxShadow = '0 4px 6px rgba(0,0,0,0.1)';
                    e.currentTarget.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.boxShadow = 'none';
                    e.currentTarget.style.transform = 'none';
                  }}
                >
                  <div style={{ marginBottom: '12px' }}>
                    <BookStatusBadge status={getDisplayStatus(book)} />
                  </div>
                  <h3
                    style={{
                      fontSize: '18px',
                      fontWeight: '600',
                      marginBottom: '8px',
                    }}
                  >
                    {book.title}
                  </h3>
                  <p style={{ color: '#6B7280', fontSize: '14px', marginBottom: '12px' }}>
                    {book.author || 'Unknown Author'}
                  </p>
                  <div style={{ fontSize: '13px', color: '#9CA3AF' }}>
                    <div>
                      {book.board} • Grade {book.grade} • {book.subject}
                    </div>
                    <div style={{ marginTop: '4px' }}>
                      {book.country}
                      {book.edition_year && ` • ${book.edition_year}`}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default BooksDashboard;
