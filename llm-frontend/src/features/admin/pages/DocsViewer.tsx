/**
 * DocsViewer - In-app documentation viewer for admins/developers.
 *
 * Two views:
 *   1. Index: lists docs grouped by functional / technical / root
 *   2. Doc: renders a single markdown doc
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { listDocs, getDocContent, DocsIndex, DocContent } from '../api/adminApi';

const CATEGORY_LABELS: Record<string, string> = {
  functional: 'Functional (User Perspective)',
  technical: 'Technical (Developer Perspective)',
  root: 'General',
};

const CATEGORY_ORDER = ['functional', 'technical', 'root'] as const;

const DocsViewer: React.FC = () => {
  const navigate = useNavigate();

  // Index state
  const [index, setIndex] = useState<DocsIndex | null>(null);
  const [indexLoading, setIndexLoading] = useState(true);
  const [indexError, setIndexError] = useState<string | null>(null);

  // Doc state
  const [doc, setDoc] = useState<DocContent | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState<string | null>(null);

  useEffect(() => {
    loadIndex();
  }, []);

  const loadIndex = async () => {
    try {
      setIndexLoading(true);
      setIndexError(null);
      const data = await listDocs();
      setIndex(data);
    } catch (err) {
      setIndexError(err instanceof Error ? err.message : 'Failed to load docs');
    } finally {
      setIndexLoading(false);
    }
  };

  const openDoc = async (category: string, filename: string) => {
    try {
      setDocLoading(true);
      setDocError(null);
      const data = await getDocContent(category, filename);
      setDoc(data);
    } catch (err) {
      setDocError(err instanceof Error ? err.message : 'Failed to load document');
    } finally {
      setDocLoading(false);
    }
  };

  const closeDoc = () => {
    setDoc(null);
    setDocError(null);
  };

  // ---------- Doc view ----------
  if (doc || docLoading || docError) {
    return (
      <div style={{ padding: '20px', maxWidth: '900px', margin: '0 auto' }}>
        <button
          onClick={closeDoc}
          style={{
            padding: '8px 16px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
            marginBottom: '20px',
          }}
        >
          &larr; Back to Docs
        </button>

        {docLoading && <p>Loading document...</p>}

        {docError && (
          <div style={{ padding: '15px', backgroundColor: '#FEE2E2', color: '#991B1B', borderRadius: '6px' }}>
            {docError}
          </div>
        )}

        {doc && (
          <div style={markdownContainerStyle}>
            <ReactMarkdown>{doc.content}</ReactMarkdown>
          </div>
        )}
      </div>
    );
  }

  // ---------- Index view ----------
  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          Documentation
        </h1>
        <p style={{ color: '#6B7280' }}>
          Browse project documentation rendered in-app
        </p>
      </div>

      {/* Nav */}
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
      </div>

      {/* Loading */}
      {indexLoading && (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          <p>Loading documentation index...</p>
        </div>
      )}

      {/* Error */}
      {indexError && (
        <div style={{ padding: '15px', backgroundColor: '#FEE2E2', color: '#991B1B', borderRadius: '6px', marginBottom: '20px' }}>
          {indexError}
        </div>
      )}

      {/* Doc index */}
      {!indexLoading && !indexError && index && (
        <div>
          {CATEGORY_ORDER.map((cat) => {
            const docs = index[cat];
            if (!docs || docs.length === 0) return null;
            return (
              <div key={cat} style={{ marginBottom: '30px' }}>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '12px', color: '#1F2937' }}>
                  {CATEGORY_LABELS[cat]}
                </h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
                  {docs.map((d) => (
                    <div
                      key={d.filename}
                      onClick={() => openDoc(cat, d.filename)}
                      style={{
                        padding: '16px',
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
                      <h3 style={{ fontSize: '16px', fontWeight: '500', color: '#1F2937' }}>
                        {d.title}
                      </h3>
                      <p style={{ fontSize: '13px', color: '#9CA3AF', marginTop: '4px' }}>
                        {cat}/{d.filename}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// Styles for rendered markdown
const markdownContainerStyle: React.CSSProperties = {
  lineHeight: '1.7',
  color: '#1F2937',
  fontSize: '15px',
};

export default DocsViewer;
