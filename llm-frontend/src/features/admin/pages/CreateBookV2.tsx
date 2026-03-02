import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createBookV2,
  saveTOC,
  extractTOCFromImages,
  CreateBookV2Request,
  TOCEntry,
} from '../api/adminApiV2';

const MAX_TOC_IMAGES = 5;

const CreateBookV2: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<'metadata' | 'toc'>('metadata');
  const [bookId, setBookId] = useState<string | null>(null);

  const [formData, setFormData] = useState<CreateBookV2Request>({
    title: '',
    author: '',
    edition: '',
    edition_year: new Date().getFullYear(),
    country: 'India',
    board: 'CBSE',
    grade: 3,
    subject: 'Mathematics',
  });

  // TOC state
  const [tocMode, setTocMode] = useState<'upload' | 'manual'>('upload');
  const [tocImages, setTocImages] = useState<File[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [extractionDone, setExtractionDone] = useState(false);
  const [rawOcrText, setRawOcrText] = useState<string>('');
  const [showOcrText, setShowOcrText] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [tocEntries, setTocEntries] = useState<TOCEntry[]>([
    { chapter_number: 1, chapter_title: '', start_page: 1, end_page: 10 },
  ]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'grade' || name === 'edition_year' ? parseInt(value) : value,
    }));
  };

  const handleCreateBook = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);
      setError(null);
      const book = await createBookV2(formData);
      setBookId(book.id);
      setStep('toc');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create book');
    } finally {
      setLoading(false);
    }
  };

  // ── TOC image upload handlers ──

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length + tocImages.length > MAX_TOC_IMAGES) {
      setError(`Maximum ${MAX_TOC_IMAGES} images allowed`);
      return;
    }
    setTocImages((prev) => [...prev, ...files]);
    setExtractionDone(false);
    setError(null);
  };

  const removeImage = (index: number) => {
    setTocImages((prev) => prev.filter((_, i) => i !== index));
    setExtractionDone(false);
  };

  const handleExtractTOC = async () => {
    if (!bookId || tocImages.length === 0) return;
    try {
      setExtracting(true);
      setError(null);
      const result = await extractTOCFromImages(bookId, tocImages);
      setTocEntries(result.chapters);
      setRawOcrText(result.raw_ocr_text);
      setExtractionDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'TOC extraction failed');
    } finally {
      setExtracting(false);
    }
  };

  // ── Manual TOC handlers ──

  const addTocEntry = () => {
    const lastEntry = tocEntries[tocEntries.length - 1];
    setTocEntries([
      ...tocEntries,
      {
        chapter_number: tocEntries.length + 1,
        chapter_title: '',
        start_page: lastEntry ? lastEntry.end_page + 1 : 1,
        end_page: lastEntry ? lastEntry.end_page + 10 : 10,
      },
    ]);
  };

  const removeTocEntry = (index: number) => {
    if (tocEntries.length <= 1) return;
    const updated = tocEntries.filter((_, i) => i !== index);
    setTocEntries(updated.map((entry, i) => ({ ...entry, chapter_number: i + 1 })));
  };

  const updateTocEntry = (index: number, field: keyof TOCEntry, value: string | number) => {
    const updated = [...tocEntries];
    const numericFields: (keyof TOCEntry)[] = ['start_page', 'end_page', 'chapter_number'];
    updated[index] = {
      ...updated[index],
      [field]: typeof value === 'string' && numericFields.includes(field)
        ? parseInt(value) || 0
        : value,
    };
    setTocEntries(updated);
  };

  const handleSaveTOC = async () => {
    if (!bookId) return;
    for (const entry of tocEntries) {
      if (!entry.chapter_title.trim()) {
        setError('All chapters must have a title');
        return;
      }
    }

    try {
      setLoading(true);
      setError(null);
      await saveTOC(bookId, tocEntries);
      navigate(`/admin/books-v2/${bookId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save TOC');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    width: '100%', padding: '8px 12px', border: '1px solid #D1D5DB',
    borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' as const,
  };

  const labelStyle = { display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 600, color: '#374151' };

  const tabStyle = (active: boolean) => ({
    padding: '8px 20px',
    border: 'none',
    borderBottom: active ? '2px solid #3B82F6' : '2px solid transparent',
    background: 'none',
    color: active ? '#3B82F6' : '#6B7280',
    fontWeight: active ? 600 : 400 as number,
    cursor: 'pointer' as const,
    fontSize: '14px',
  });

  // ── Table editor (shared between upload + manual modes) ──

  const renderTocTable = () => (
    <>
      <div style={{ marginBottom: '16px' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '50px 1fr 80px 80px 40px',
          gap: '8px', padding: '8px 0', borderBottom: '2px solid #E5E7EB',
          fontWeight: 600, fontSize: '13px', color: '#374151',
        }}>
          <div>#</div>
          <div>Chapter Title</div>
          <div>Start</div>
          <div>End</div>
          <div></div>
        </div>

        {tocEntries.map((entry, index) => (
          <div key={index} style={{ borderBottom: '1px solid #F3F4F6' }}>
            <div
              style={{
                display: 'grid', gridTemplateColumns: '50px 1fr 80px 80px 40px',
                gap: '8px', padding: '8px 0',
                alignItems: 'center',
              }}
            >
              <div style={{ color: '#6B7280', fontWeight: 600 }}>{entry.chapter_number}</div>
              <input
                type="text"
                value={entry.chapter_title}
                onChange={(e) => updateTocEntry(index, 'chapter_title', e.target.value)}
                placeholder="Chapter title"
                style={{ ...inputStyle, padding: '6px 8px' }}
              />
              <input
                type="number"
                value={entry.start_page}
                onChange={(e) => updateTocEntry(index, 'start_page', e.target.value)}
                min="1"
                style={{ ...inputStyle, padding: '6px 8px' }}
              />
              <input
                type="number"
                value={entry.end_page}
                onChange={(e) => updateTocEntry(index, 'end_page', e.target.value)}
                min="1"
                style={{ ...inputStyle, padding: '6px 8px' }}
              />
              <button
                onClick={() => removeTocEntry(index)}
                disabled={tocEntries.length <= 1}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: tocEntries.length <= 1 ? '#D1D5DB' : '#EF4444',
                  fontSize: '18px',
                }}
              >
                &times;
              </button>
            </div>
            {/* Notes sub-row */}
            <div style={{ paddingLeft: '50px', paddingBottom: '8px', paddingRight: '48px' }}>
              <input
                type="text"
                value={entry.notes || ''}
                onChange={(e) => updateTocEntry(index, 'notes', e.target.value || '')}
                placeholder="Notes (themes, subtopics, activities...)"
                style={{
                  ...inputStyle, padding: '4px 8px', fontSize: '12px',
                  color: '#6B7280', backgroundColor: '#F9FAFB',
                }}
              />
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={addTocEntry}
        style={{
          background: 'none', border: '1px dashed #D1D5DB', color: '#3B82F6',
          padding: '8px 16px', borderRadius: '6px', cursor: 'pointer',
          width: '100%', marginBottom: '24px',
        }}
      >
        + Add Chapter
      </button>
    </>
  );

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto' }}>
      <button
        onClick={() => navigate('/admin/books-v2')}
        style={{ background: 'none', border: 'none', color: '#3B82F6', cursor: 'pointer', marginBottom: '16px', fontSize: '14px' }}
      >
        &larr; Back to V2 Dashboard
      </button>

      <h1 style={{ margin: '0 0 4px', fontSize: '24px' }}>Create New Book (V2)</h1>
      <p style={{ color: '#6B7280', marginTop: 0 }}>
        {step === 'metadata' ? 'Step 1: Book metadata' : 'Step 2: Table of Contents'}
      </p>

      {error && (
        <div style={{ backgroundColor: '#FEE2E2', color: '#991B1B', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {step === 'metadata' && (
        <form onSubmit={handleCreateBook}>
          <div style={{ backgroundColor: 'white', padding: '24px', border: '1px solid #E5E7EB', borderRadius: '12px' }}>
            <div style={{ marginBottom: '20px' }}>
              <label style={labelStyle}>Book Title *</label>
              <input type="text" name="title" value={formData.title} onChange={handleChange} required placeholder="e.g., Math Magic" style={inputStyle} />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={labelStyle}>Author</label>
              <input type="text" name="author" value={formData.author} onChange={handleChange} placeholder="e.g., NCERT" style={inputStyle} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
              <div>
                <label style={labelStyle}>Edition</label>
                <input type="text" name="edition" value={formData.edition} onChange={handleChange} style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Edition Year</label>
                <input type="number" name="edition_year" value={formData.edition_year} onChange={handleChange} style={inputStyle} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
              <div>
                <label style={labelStyle}>Country *</label>
                <input type="text" name="country" value={formData.country} onChange={handleChange} required style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Board *</label>
                <select name="board" value={formData.board} onChange={handleChange} style={inputStyle}>
                  <option value="CBSE">CBSE</option>
                  <option value="ICSE">ICSE</option>
                  <option value="State Board">State Board</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
              <div>
                <label style={labelStyle}>Grade *</label>
                <input type="number" name="grade" value={formData.grade} onChange={handleChange} min="1" max="12" required style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Subject *</label>
                <select name="subject" value={formData.subject} onChange={handleChange} style={inputStyle}>
                  <option value="Mathematics">Mathematics</option>
                  <option value="Science">Science</option>
                  <option value="English">English</option>
                  <option value="Hindi">Hindi</option>
                  <option value="Social Studies">Social Studies</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="submit"
                disabled={loading}
                style={{
                  backgroundColor: '#3B82F6', color: 'white', border: 'none',
                  padding: '10px 24px', borderRadius: '8px', cursor: 'pointer',
                  fontWeight: 600, opacity: loading ? 0.6 : 1,
                }}
              >
                {loading ? 'Creating...' : 'Next: Define TOC'}
              </button>
              <button
                type="button"
                onClick={() => navigate('/admin/books-v2')}
                disabled={loading}
                style={{
                  backgroundColor: '#F3F4F6', border: '1px solid #D1D5DB',
                  padding: '10px 20px', borderRadius: '8px', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </form>
      )}

      {step === 'toc' && (
        <div style={{ backgroundColor: 'white', padding: '24px', border: '1px solid #E5E7EB', borderRadius: '12px' }}>
          {/* Tab selector */}
          <div style={{ display: 'flex', borderBottom: '1px solid #E5E7EB', marginBottom: '20px' }}>
            <button
              onClick={() => { setTocMode('upload'); setError(null); }}
              style={tabStyle(tocMode === 'upload')}
            >
              Upload TOC Pages
            </button>
            <button
              onClick={() => { setTocMode('manual'); setError(null); }}
              style={tabStyle(tocMode === 'manual')}
            >
              Manual Entry
            </button>
          </div>

          {/* Upload mode */}
          {tocMode === 'upload' && (
            <>
              <p style={{ color: '#6B7280', fontSize: '14px', marginTop: 0 }}>
                Upload screenshots of your book's Table of Contents pages. The AI will extract chapters automatically.
              </p>

              {/* Image upload area */}
              <div
                onClick={() => !extracting && fileInputRef.current?.click()}
                style={{
                  border: '2px dashed #D1D5DB',
                  borderRadius: '8px',
                  padding: '24px',
                  textAlign: 'center',
                  cursor: extracting ? 'not-allowed' : 'pointer',
                  marginBottom: '16px',
                  backgroundColor: '#F9FAFB',
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={handleImageSelect}
                  style={{ display: 'none' }}
                />
                <p style={{ margin: 0, color: '#6B7280', fontSize: '14px' }}>
                  Click to select TOC page images (1-{MAX_TOC_IMAGES} images, PNG/JPG/WEBP)
                </p>
              </div>

              {/* Image list */}
              {tocImages.length > 0 && (
                <div style={{ marginBottom: '16px' }}>
                  {tocImages.map((file, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '8px 12px', backgroundColor: '#F3F4F6', borderRadius: '6px',
                        marginBottom: '4px', fontSize: '13px',
                      }}
                    >
                      <span style={{ color: '#374151' }}>
                        {file.name} ({(file.size / 1024).toFixed(0)} KB)
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); removeImage(i); }}
                        disabled={extracting}
                        style={{
                          background: 'none', border: 'none', color: '#EF4444',
                          cursor: 'pointer', fontSize: '16px',
                        }}
                      >
                        &times;
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Extract button */}
              {tocImages.length > 0 && !extractionDone && (
                <button
                  onClick={handleExtractTOC}
                  disabled={extracting}
                  style={{
                    backgroundColor: '#8B5CF6', color: 'white', border: 'none',
                    padding: '10px 24px', borderRadius: '8px', cursor: 'pointer',
                    fontWeight: 600, opacity: extracting ? 0.7 : 1,
                    width: '100%', marginBottom: '16px',
                  }}
                >
                  {extracting ? 'Extracting TOC... (this takes ~15-20 seconds)' : 'Extract TOC'}
                </button>
              )}

              {/* Extraction spinner */}
              {extracting && (
                <div style={{
                  textAlign: 'center', padding: '16px', color: '#6B7280', fontSize: '13px',
                }}>
                  OCR + AI extraction in progress. Please wait...
                </div>
              )}

              {/* After extraction: show table editor for review */}
              {extractionDone && (
                <>
                  <div style={{
                    backgroundColor: '#ECFDF5', color: '#065F46', padding: '10px 14px',
                    borderRadius: '8px', marginBottom: '16px', fontSize: '13px',
                  }}>
                    Extracted {tocEntries.length} chapter(s). Review and edit below, then save.
                  </div>

                  {renderTocTable()}

                  {/* Collapsible raw OCR text */}
                  {rawOcrText && (
                    <div style={{ marginBottom: '16px' }}>
                      <button
                        onClick={() => setShowOcrText(!showOcrText)}
                        style={{
                          background: 'none', border: 'none', color: '#6B7280',
                          cursor: 'pointer', fontSize: '12px', padding: 0,
                          textDecoration: 'underline',
                        }}
                      >
                        {showOcrText ? 'Hide' : 'Show'} Raw OCR Text
                      </button>
                      {showOcrText && (
                        <pre style={{
                          backgroundColor: '#F3F4F6', padding: '12px', borderRadius: '6px',
                          fontSize: '11px', maxHeight: '200px', overflow: 'auto',
                          whiteSpace: 'pre-wrap', marginTop: '8px', color: '#374151',
                        }}>
                          {rawOcrText}
                        </pre>
                      )}
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {/* Manual mode */}
          {tocMode === 'manual' && (
            <>
              <p style={{ color: '#6B7280', fontSize: '14px', marginTop: 0 }}>
                Define the Table of Contents manually. Each chapter needs a title and page range.
              </p>
              {renderTocTable()}
            </>
          )}

          {/* Save button (shared) */}
          {(tocMode === 'manual' || extractionDone) && (
            <div>
              <button
                onClick={handleSaveTOC}
                disabled={loading}
                style={{
                  backgroundColor: '#10B981', color: 'white', border: 'none',
                  padding: '10px 24px', borderRadius: '8px', cursor: 'pointer',
                  fontWeight: 600, opacity: loading ? 0.6 : 1,
                }}
              >
                {loading ? 'Saving...' : 'Save TOC & Continue'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default CreateBookV2;
