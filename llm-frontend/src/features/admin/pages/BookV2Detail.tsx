import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, deleteBookV2, uploadPageV2, deletePageV2, getChapterPages,
  startProcessing, reprocessChapter, refinalizeChapter,
  getLatestJobV2, getChapterTopics, syncChapter, syncBook,
  getPageDetailV2, retryPageOcrV2, generateExplanations,
  BookV2DetailResponse, ChapterResponseV2, PageResponseV2,
  ProcessingJobResponseV2, ChapterTopicResponseV2, PageDetailResponseV2,
  SyncResponseV2, ExplanationGenerationResponse,
} from '../api/adminApiV2';

const POLL_INTERVAL = 3000;

const STATUS_BADGE: Record<string, { bg: string; color: string; label: string }> = {
  toc_defined: { bg: '#F3F4F6', color: '#374151', label: 'TOC Defined' },
  upload_in_progress: { bg: '#FEF3C7', color: '#92400E', label: 'Uploading' },
  upload_complete: { bg: '#DBEAFE', color: '#1D4ED8', label: 'Ready to Process' },
  topic_extraction: { bg: '#EDE9FE', color: '#5B21B6', label: 'Extracting Topics' },
  chapter_finalizing: { bg: '#EDE9FE', color: '#5B21B6', label: 'Finalizing' },
  chapter_completed: { bg: '#D1FAE5', color: '#065F46', label: 'Completed' },
  failed: { bg: '#FEE2E2', color: '#991B1B', label: 'Failed' },
};

const BookV2Detail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [book, setBook] = useState<BookV2DetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedChapter, setExpandedChapter] = useState<string | null>(null);
  const [chapterPages, setChapterPages] = useState<Record<string, PageResponseV2[]>>({});
  const [chapterJobs, setChapterJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [chapterTopics, setChapterTopics] = useState<Record<string, ChapterTopicResponseV2[]>>({});
  const [activeTab, setActiveTab] = useState<'chapters' | 'results'>('chapters');
  const [deleting, setDeleting] = useState(false);
  const [uploadingChapter, setUploadingChapter] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; pageNum: number } | null>(null);
  const [selectedPage, setSelectedPage] = useState<{ chapterId: string; pageNum: number; chapter: ChapterResponseV2 } | null>(null);
  const [pageDetail, setPageDetail] = useState<PageDetailResponseV2 | null>(null);
  const [pageDetailLoading, setPageDetailLoading] = useState(false);
  const [reuploadingPage, setReuploadingPage] = useState(false);
  const [retryingOcr, setRetryingOcr] = useState(false);
  const [expandedTopicId, setExpandedTopicId] = useState<string | null>(null);
  const [syncingChapterId, setSyncingChapterId] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<Record<string, SyncResponseV2>>({});
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncAllResult, setSyncAllResult] = useState<SyncResponseV2 | null>(null);
  const [generatingExplanations, setGeneratingExplanations] = useState<string | null>(null);
  const [explanationResult, setExplanationResult] = useState<Record<string, ExplanationGenerationResponse>>({});
  const pollingRef = useRef<Record<string, NodeJS.Timeout>>({});
  const pollingDoneRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (id) loadBook(true);
    return () => {
      Object.values(pollingRef.current).forEach(clearInterval);
    };
  }, [id]);

  const loadBook = async (isInitial = false) => {
    if (!id) return;
    try {
      if (isInitial) setLoading(true);
      setError(null);
      const data = await getBookV2(id);
      setBook(data);
      // Start polling for any chapters in processing state (only if not already polling)
      for (const ch of data.chapters) {
        if (['topic_extraction', 'chapter_finalizing'].includes(ch.status)) {
          startPolling(ch.id);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load book');
    } finally {
      if (isInitial) setLoading(false);
    }
  };

  const startPolling = useCallback((chapterId: string) => {
    if (!id || pollingRef.current[chapterId] || pollingDoneRef.current.has(chapterId)) return;
    const poll = async () => {
      try {
        const job = await getLatestJobV2(id!, chapterId);
        setChapterJobs(prev => ({ ...prev, [chapterId]: job }));
        if (job.status === 'completed' || job.status === 'failed' || job.status === 'completed_with_errors') {
          clearInterval(pollingRef.current[chapterId]);
          delete pollingRef.current[chapterId];
          pollingDoneRef.current.add(chapterId);
          // Final refresh to get updated chapter status
          loadBook();
        }
      } catch { /* ignore polling errors */ }
    };
    // Immediate first fetch, then every POLL_INTERVAL
    poll();
    pollingRef.current[chapterId] = setInterval(poll, POLL_INTERVAL);
  }, [id]);

  const handleDeleteBook = async () => {
    if (!id || !book) return;
    if (!confirm(`Delete "${book.title}" and all its data?`)) return;
    try {
      setDeleting(true);
      await deleteBookV2(id);
      navigate('/admin/books-v2');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete');
      setDeleting(false);
    }
  };

  const handleExpandChapter = async (ch: ChapterResponseV2) => {
    const chId = ch.id;
    if (expandedChapter === chId) { setExpandedChapter(null); return; }
    setExpandedChapter(chId);
    // Load pages and topics
    if (!chapterPages[chId]) {
      try {
        const pagesResp = await getChapterPages(id!, chId);
        setChapterPages(prev => ({ ...prev, [chId]: pagesResp.pages }));
      } catch { /* ignore */ }
    }
    if (ch.status === 'chapter_completed' && !chapterTopics[chId]) {
      try {
        const topicsResp = await getChapterTopics(id!, chId);
        setChapterTopics(prev => ({ ...prev, [chId]: topicsResp.topics }));
      } catch { /* ignore */ }
    }
  };

  const handleUpload = async (ch: ChapterResponseV2, files: FileList) => {
    if (!id) return;
    const existingPages = chapterPages[ch.id] || [];
    const uploadedNums = new Set(existingPages.map(p => p.page_number));
    let nextPage = ch.start_page;
    while (uploadedNums.has(nextPage) && nextPage <= ch.end_page) nextPage++;

    const filesToUpload = Math.min(files.length, ch.end_page - nextPage + 1);
    setUploadingChapter(ch.id);
    setError(null);

    for (let i = 0; i < filesToUpload; i++) {
      const pageNum = nextPage + i;
      setUploadProgress({ current: i + 1, total: filesToUpload, pageNum });
      try {
        await uploadPageV2(id, ch.id, pageNum, files[i]);
        // Refresh page grid after each successful upload
        const pagesResp = await getChapterPages(id, ch.id);
        setChapterPages(prev => ({ ...prev, [ch.id]: pagesResp.pages }));
      } catch (err) {
        setError(`Upload failed for page ${pageNum}: ${err instanceof Error ? err.message : 'Unknown error'}`);
        break;
      }
    }
    setUploadingChapter(null);
    setUploadProgress(null);
    loadBook();
  };

  const handleStartProcessing = async (ch: ChapterResponseV2) => {
    if (!id) return;
    try {
      setExpandedChapter(ch.id);
      const job = await startProcessing(id, ch.id, ch.status === 'failed');
      setChapterJobs(prev => ({ ...prev, [ch.id]: job }));
      pollingDoneRef.current.delete(ch.id);
      startPolling(ch.id);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start processing');
    }
  };

  const handleSyncChapter = async (ch: ChapterResponseV2) => {
    if (!id) return;
    setSyncingChapterId(ch.id);
    try {
      const result = await syncChapter(id, ch.id);
      setSyncResult(prev => ({ ...prev, [ch.id]: result }));
    } catch (err) {
      setSyncResult(prev => ({
        ...prev,
        [ch.id]: { synced_chapters: 0, synced_topics: 0, errors: [err instanceof Error ? err.message : 'Sync failed'] },
      }));
    } finally {
      setSyncingChapterId(null);
    }
  };

  const handleSyncAll = async () => {
    if (!id) return;
    setSyncingAll(true);
    try {
      const result = await syncBook(id);
      setSyncAllResult(result);
    } catch (err) {
      setSyncAllResult({ synced_chapters: 0, synced_topics: 0, errors: [err instanceof Error ? err.message : 'Sync failed'] });
    } finally {
      setSyncingAll(false);
    }
  };

  const handleReprocess = async (ch: ChapterResponseV2) => {
    if (!id) return;
    if (!confirm(`Reprocess "${ch.chapter_title}" from scratch? This will wipe existing topics.`)) return;
    try {
      const job = await reprocessChapter(id, ch.id);
      setChapterJobs(prev => ({ ...prev, [ch.id]: job }));
      pollingDoneRef.current.delete(ch.id);
      startPolling(ch.id);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reprocess failed');
    }
  };

  const handleRefinalize = async (ch: ChapterResponseV2) => {
    if (!id) return;
    try {
      const job = await refinalizeChapter(id, ch.id);
      setChapterJobs(prev => ({ ...prev, [ch.id]: job }));
      pollingDoneRef.current.delete(ch.id);
      startPolling(ch.id);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refinalize failed');
    }
  };

  const handleGenerateExplanations = async (ch: ChapterResponseV2) => {
    if (!id) return;
    setGeneratingExplanations(ch.id);
    try {
      const result = await generateExplanations(id, ch.id);
      setExplanationResult(prev => ({ ...prev, [ch.id]: result }));
    } catch (err) {
      setExplanationResult(prev => ({
        ...prev,
        [ch.id]: { generated: 0, skipped: 0, failed: 1, errors: [err instanceof Error ? err.message : 'Generation failed'] },
      }));
    } finally {
      setGeneratingExplanations(null);
    }
  };

  const handleOpenPageDetail = async (ch: ChapterResponseV2, pageNum: number) => {
    if (!id) return;
    setSelectedPage({ chapterId: ch.id, pageNum, chapter: ch });
    setPageDetail(null);
    setPageDetailLoading(true);
    try {
      const detail = await getPageDetailV2(id, ch.id, pageNum);
      setPageDetail(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load page detail');
      setSelectedPage(null);
    } finally {
      setPageDetailLoading(false);
    }
  };

  const handleDeletePage = async (ch: ChapterResponseV2, pageNum: number) => {
    if (!id) return;
    if (!confirm(`Delete page ${pageNum}?`)) return;
    try {
      await deletePageV2(id, ch.id, pageNum);
      const pagesResp = await getChapterPages(id, ch.id);
      setChapterPages(prev => ({ ...prev, [ch.id]: pagesResp.pages }));
      setSelectedPage(null);
      setPageDetail(null);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete page failed');
    }
  };

  const handleReuploadPage = async (ch: ChapterResponseV2, pageNum: number, file: File) => {
    if (!id) return;
    setReuploadingPage(true);
    try {
      // Delete old page first
      await deletePageV2(id, ch.id, pageNum);
      // Upload new page
      await uploadPageV2(id, ch.id, pageNum, file);
      // Refresh pages
      const pagesResp = await getChapterPages(id, ch.id);
      setChapterPages(prev => ({ ...prev, [ch.id]: pagesResp.pages }));
      // Reload page detail
      const detail = await getPageDetailV2(id, ch.id, pageNum);
      setPageDetail(detail);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Re-upload failed');
    } finally {
      setReuploadingPage(false);
    }
  };

  const handleRetryOcr = async (ch: ChapterResponseV2, pageNum: number) => {
    if (!id) return;
    setRetryingOcr(true);
    try {
      await retryPageOcrV2(id, ch.id, pageNum);
      // Reload page detail
      const detail = await getPageDetailV2(id, ch.id, pageNum);
      setPageDetail(detail);
      // Refresh pages list
      const pagesResp = await getChapterPages(id, ch.id);
      setChapterPages(prev => ({ ...prev, [ch.id]: pagesResp.pages }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retry OCR failed');
    } finally {
      setRetryingOcr(false);
    }
  };

  if (loading) return <div style={{ padding: '40px', textAlign: 'center' }}>Loading...</div>;
  if (error && !book) return <div style={{ padding: '40px', textAlign: 'center', color: '#991B1B' }}>{error}</div>;
  if (!book) return <div style={{ padding: '40px', textAlign: 'center' }}>Book not found</div>;

  const completedChapters = book.chapters.filter(ch => ch.status === 'chapter_completed').length;

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <button onClick={() => navigate('/admin/books-v2')} style={{ background: 'none', border: 'none', color: '#3B82F6', cursor: 'pointer', marginBottom: '12px', fontSize: '14px' }}>
        &larr; Back to V2 Dashboard
      </button>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '20px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '22px' }}>{book.title}</h1>
          <p style={{ color: '#6B7280', margin: '4px 0' }}>
            {book.author} &bull; {book.board} &bull; Grade {book.grade} &bull; {book.subject}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={loadBook} style={{ backgroundColor: '#F3F4F6', border: '1px solid #D1D5DB', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
            Refresh
          </button>
          {completedChapters > 0 && (
            <button onClick={handleSyncAll} disabled={syncingAll} style={{ backgroundColor: '#10B981', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: syncingAll ? 'wait' : 'pointer', fontSize: '13px', opacity: syncingAll ? 0.6 : 1 }}>
              {syncingAll ? 'Syncing...' : 'Sync All to DB'}
            </button>
          )}
          <button onClick={handleDeleteBook} disabled={deleting} style={{ backgroundColor: '#FEE2E2', color: '#991B1B', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
            {deleting ? 'Deleting...' : 'Delete Book'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ backgroundColor: '#FEE2E2', color: '#991B1B', padding: '12px 16px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
          <button onClick={() => setError(null)} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>&times;</button>
        </div>
      )}

      {syncAllResult && (
        <div style={{
          backgroundColor: syncAllResult.errors.length > 0 ? '#FEE2E2' : '#D1FAE5',
          color: syncAllResult.errors.length > 0 ? '#991B1B' : '#065F46',
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
        }}>
          <button onClick={() => setSyncAllResult(null)} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit' }}>&times;</button>
          {syncAllResult.errors.length > 0
            ? <>Sync completed with errors. Synced {syncAllResult.synced_chapters} chapters, {syncAllResult.synced_topics} topics.
              <ul style={{ margin: '8px 0 0', paddingLeft: '20px' }}>
                {syncAllResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </>
            : <>Synced {syncAllResult.synced_chapters} chapters, {syncAllResult.synced_topics} topics to teaching guidelines.</>
          }
        </div>
      )}

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
        {[
          { label: 'Total Chapters', value: book.chapters.length },
          { label: 'Completed', value: completedChapters },
          { label: 'In Progress', value: book.chapters.filter(ch => ['upload_in_progress', 'topic_extraction', 'chapter_finalizing'].includes(ch.status)).length },
        ].map(stat => (
          <div key={stat.label} style={{ backgroundColor: 'white', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '16px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', fontWeight: 700 }}>{stat.value}</div>
            <div style={{ fontSize: '13px', color: '#6B7280' }}>{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Chapter Cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {book.chapters.map((ch) => {
          const badge = STATUS_BADGE[ch.status] || STATUS_BADGE.toc_defined;
          const isExpanded = expandedChapter === ch.id;
          const job = chapterJobs[ch.id];
          const pages = chapterPages[ch.id] || [];
          const topics = chapterTopics[ch.id] || [];

          return (
            <div key={ch.id} style={{ backgroundColor: 'white', border: '1px solid #E5E7EB', borderRadius: '10px', overflow: 'hidden' }}>
              {/* Chapter Header */}
              <div
                onClick={() => handleExpandChapter(ch)}
                style={{ padding: '16px 20px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: '#9CA3AF' }}>{isExpanded ? '▼' : '▶'}</span>
                  <div>
                    <span style={{ fontWeight: 600 }}>Chapter {ch.chapter_number}: {ch.chapter_title}</span>
                    <span style={{ color: '#9CA3AF', fontSize: '13px', marginLeft: '8px' }}>pp. {ch.start_page}-{ch.end_page}</span>
                    {ch.display_name && ch.display_name !== ch.chapter_title && (
                      <div style={{ fontSize: '12px', color: '#6B7280', fontStyle: 'italic' }}>{ch.display_name}</div>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ fontSize: '13px', color: '#6B7280' }}>{ch.uploaded_page_count}/{ch.total_pages} pages</span>
                  <span style={{ backgroundColor: badge.bg, color: badge.color, padding: '3px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600 }}>
                    {badge.label}
                  </span>
                </div>
              </div>

              {/* Processing progress — always visible when job is active */}
              {job && ['pending', 'running'].includes(job.status) && (
                <div style={{ borderTop: '1px solid #E5E7EB', padding: '12px 20px', backgroundColor: '#F5F3FF' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <div style={{ fontWeight: 600, fontSize: '13px', color: '#5B21B6' }}>
                      {job.current_item || 'Starting...'}
                    </div>
                    {job.total_items ? (
                      <span style={{ fontSize: '12px', color: '#6D28D9', fontWeight: 600 }}>
                        {job.completed_items}/{job.total_items} chunks
                        {job.failed_items > 0 && <span style={{ color: '#DC2626' }}> ({job.failed_items} failed)</span>}
                      </span>
                    ) : null}
                  </div>
                  {job.total_items ? (
                    <div style={{ height: '6px', backgroundColor: '#DDD6FE', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', backgroundColor: '#7C3AED', borderRadius: '3px',
                        width: `${(job.completed_items / job.total_items) * 100}%`,
                        transition: 'width 0.5s ease',
                      }} />
                    </div>
                  ) : (
                    <div style={{ height: '6px', backgroundColor: '#DDD6FE', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', backgroundColor: '#7C3AED', borderRadius: '3px', width: '30%',
                        animation: 'pulse 1.5s ease-in-out infinite',
                      }} />
                    </div>
                  )}
                </div>
              )}

              {/* Expanded Content */}
              {isExpanded && (
                <div style={{ borderTop: '1px solid #E5E7EB', padding: '16px 20px' }}>
                  {/* Upload progress bar */}
                  <div style={{ marginBottom: '12px' }}>
                    <div style={{ height: '6px', backgroundColor: '#E5E7EB', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', backgroundColor: ch.uploaded_page_count === ch.total_pages ? '#10B981' : '#3B82F6',
                        width: `${(ch.uploaded_page_count / ch.total_pages) * 100}%`, transition: 'width 0.3s',
                      }} />
                    </div>
                  </div>

                  {/* Chapter summary for completed chapters */}
                  {ch.status === 'chapter_completed' && ch.summary && (
                    <div style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', borderRadius: '8px', padding: '12px 16px', marginBottom: '12px' }}>
                      {ch.display_name && ch.display_name !== ch.chapter_title && (
                        <div style={{ fontWeight: 600, fontSize: '14px', color: '#065F46', marginBottom: '4px' }}>
                          {ch.display_name}
                        </div>
                      )}
                      <p style={{ margin: 0, fontSize: '13px', color: '#047857', lineHeight: '1.5' }}>{ch.summary}</p>
                    </div>
                  )}

                  {/* Error display */}
                  {ch.error_message && (
                    <div style={{ backgroundColor: '#FEE2E2', padding: '10px', borderRadius: '6px', marginBottom: '12px', fontSize: '13px', color: '#991B1B' }}>
                      {ch.error_message}
                    </div>
                  )}

                  {/* Upload area */}
                  {['toc_defined', 'upload_in_progress'].includes(ch.status) && (
                    <div style={{ marginBottom: '12px' }}>
                      {uploadingChapter === ch.id && uploadProgress ? (
                        <div style={{
                          padding: '16px 20px', backgroundColor: '#EFF6FF', border: '2px solid #BFDBFE',
                          borderRadius: '8px', textAlign: 'center',
                        }}>
                          <div style={{ fontWeight: 600, fontSize: '14px', color: '#1D4ED8', marginBottom: '8px' }}>
                            Uploading page {uploadProgress.pageNum} ({uploadProgress.current} of {uploadProgress.total})
                          </div>
                          <div style={{ height: '6px', backgroundColor: '#DBEAFE', borderRadius: '3px', overflow: 'hidden', marginBottom: '6px' }}>
                            <div style={{
                              height: '100%', backgroundColor: '#3B82F6', borderRadius: '3px',
                              width: `${(uploadProgress.current / uploadProgress.total) * 100}%`,
                              transition: 'width 0.3s',
                            }} />
                          </div>
                          <div style={{ fontSize: '12px', color: '#6B7280' }}>
                            Each page takes ~20-30s (upload + OCR). Please wait...
                          </div>
                        </div>
                      ) : (
                        <>
                          <input
                            type="file"
                            accept="image/*"
                            multiple
                            onChange={(e) => e.target.files && handleUpload(ch, e.target.files)}
                            style={{ display: 'none' }}
                            id={`upload-${ch.id}`}
                          />
                          <label
                            htmlFor={`upload-${ch.id}`}
                            style={{
                              display: 'block', padding: '20px', textAlign: 'center',
                              border: '2px dashed #D1D5DB', borderRadius: '8px', cursor: 'pointer',
                              color: '#6B7280', fontSize: '14px',
                            }}
                          >
                            Drop page images here or click to upload
                          </label>
                        </>
                      )}
                    </div>
                  )}

                  {/* Page grid */}
                  {pages.length > 0 && (
                    <div style={{ marginBottom: '12px' }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '6px', color: '#374151' }}>Uploaded Pages</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                        {Array.from({ length: ch.total_pages }, (_, i) => ch.start_page + i).map(pn => {
                          const page = pages.find(p => p.page_number === pn);
                          return (
                            <div
                              key={pn}
                              title={page ? `Page ${pn} (${page.ocr_status}) — click to view` : `Page ${pn} — not uploaded`}
                              onClick={page ? () => handleOpenPageDetail(ch, pn) : undefined}
                              style={{
                                width: '28px', height: '28px', borderRadius: '4px', fontSize: '11px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                cursor: page ? 'pointer' : 'default',
                                backgroundColor: page
                                  ? page.ocr_status === 'completed' ? '#D1FAE5'
                                  : page.ocr_status === 'failed' ? '#FEE2E2'
                                  : '#FEF3C7'
                                  : '#F3F4F6',
                                color: page ? '#065F46' : '#9CA3AF',
                                fontWeight: page ? 600 : 400,
                              }}
                            >
                              {pn}
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ fontSize: '11px', color: '#9CA3AF', marginTop: '4px' }}>
                        Click a page to view image and OCR text
                      </div>
                    </div>
                  )}

                  {/* Action buttons — hidden while a job is actively running */}
                  {!(job && ['pending', 'running'].includes(job.status)) && (
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {ch.status === 'upload_complete' && (
                      <button onClick={() => handleStartProcessing(ch)} style={{ backgroundColor: '#7C3AED', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                        Start Processing
                      </button>
                    )}
                    {ch.status === 'failed' && (
                      <>
                        <button onClick={() => handleStartProcessing(ch)} style={{ backgroundColor: '#F59E0B', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          Resume
                        </button>
                        <button onClick={() => handleReprocess(ch)} style={{ backgroundColor: '#EF4444', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                          Reprocess
                        </button>
                      </>
                    )}
                    {ch.status === 'chapter_completed' && (
                      <>
                        <button onClick={() => handleSyncChapter(ch)} disabled={syncingChapterId === ch.id} style={{ backgroundColor: '#10B981', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: syncingChapterId === ch.id ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600, opacity: syncingChapterId === ch.id ? 0.6 : 1 }}>
                          {syncingChapterId === ch.id ? 'Syncing...' : 'Sync to DB'}
                        </button>
                        <button onClick={() => handleRefinalize(ch)} style={{ backgroundColor: '#6366F1', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
                          Re-finalize
                        </button>
                        <button onClick={() => handleReprocess(ch)} style={{ backgroundColor: '#F3F4F6', color: '#374151', border: '1px solid #D1D5DB', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
                          Reprocess
                        </button>
                        <button onClick={() => handleGenerateExplanations(ch)} disabled={generatingExplanations === ch.id} style={{ backgroundColor: '#8B5CF6', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: generatingExplanations === ch.id ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600, opacity: generatingExplanations === ch.id ? 0.6 : 1 }}>
                          {generatingExplanations === ch.id ? 'Generating...' : 'Generate Explanations'}
                        </button>
                      </>
                    )}
                  </div>
                  )}

                  {/* Explanation generation result banner */}
                  {explanationResult[ch.id] && (
                    <div style={{
                      marginTop: '12px',
                      backgroundColor: explanationResult[ch.id].errors.length > 0 ? '#FEF3C7' : '#EDE9FE',
                      color: explanationResult[ch.id].errors.length > 0 ? '#92400E' : '#5B21B6',
                      padding: '10px 14px', borderRadius: '6px', fontSize: '13px',
                    }}>
                      <button onClick={() => setExplanationResult(prev => { const next = { ...prev }; delete next[ch.id]; return next; })} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit' }}>&times;</button>
                      Explanations: {explanationResult[ch.id].generated} generated, {explanationResult[ch.id].skipped} skipped, {explanationResult[ch.id].failed} failed.
                      {explanationResult[ch.id].errors.length > 0 && (
                        <ul style={{ margin: '4px 0 0', paddingLeft: '20px' }}>
                          {explanationResult[ch.id].errors.map((e, i) => <li key={i}>{e}</li>)}
                        </ul>
                      )}
                    </div>
                  )}

                  {/* Sync result banner */}
                  {syncResult[ch.id] && (
                    <div style={{
                      marginTop: '12px',
                      backgroundColor: syncResult[ch.id].errors.length > 0 ? '#FEE2E2' : '#D1FAE5',
                      color: syncResult[ch.id].errors.length > 0 ? '#991B1B' : '#065F46',
                      padding: '10px 14px', borderRadius: '6px', fontSize: '13px',
                    }}>
                      <button onClick={() => setSyncResult(prev => { const next = { ...prev }; delete next[ch.id]; return next; })} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit' }}>&times;</button>
                      {syncResult[ch.id].errors.length > 0
                        ? <>Sync failed:
                          <ul style={{ margin: '4px 0 0', paddingLeft: '20px' }}>
                            {syncResult[ch.id].errors.map((e, i) => <li key={i}>{e}</li>)}
                          </ul>
                        </>
                        : <>Synced {syncResult[ch.id].synced_topics} topics to teaching guidelines.</>
                      }
                    </div>
                  )}

                  {/* Topics list */}
                  {topics.length > 0 && (
                    <div style={{ marginTop: '16px' }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px', color: '#374151' }}>
                        Topics ({topics.length})
                      </div>
                      {topics.map((topic, i) => {
                        const isTopicExpanded = expandedTopicId === topic.id;
                        const topicStatusBadge = (() => {
                          const s = topic.status;
                          if (s === 'final' || s === 'approved') return { bg: '#D1FAE5', color: '#065F46' };
                          if (s === 'consolidated') return { bg: '#DBEAFE', color: '#1D4ED8' };
                          return { bg: '#FEF3C7', color: '#92400E' }; // draft or other
                        })();
                        return (
                          <div key={topic.id} style={{ backgroundColor: '#F9FAFB', borderRadius: '6px', marginBottom: '6px', overflow: 'hidden' }}>
                            <div
                              onClick={() => setExpandedTopicId(isTopicExpanded ? null : topic.id)}
                              style={{ padding: '10px 12px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{isTopicExpanded ? '▼' : '▶'}</span>
                                <span style={{ fontWeight: 600, fontSize: '14px' }}>
                                  {topic.sequence_order || i + 1}. {topic.topic_title}
                                </span>
                              </div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ backgroundColor: topicStatusBadge.bg, color: topicStatusBadge.color, padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 600 }}>
                                  {topic.status}
                                </span>
                                <span style={{ fontSize: '11px', color: '#9CA3AF' }}>v{topic.version}</span>
                                <span style={{ fontSize: '12px', color: '#6B7280' }}>
                                  pp. {topic.source_page_start}-{topic.source_page_end}
                                </span>
                              </div>
                            </div>
                            {isTopicExpanded && (
                              <div style={{ padding: '0 12px 12px', borderTop: '1px solid #E5E7EB' }}>
                                <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: '#6B7280', padding: '8px 0', flexWrap: 'wrap' }}>
                                  <span><strong>Key:</strong> {topic.topic_key}</span>
                                  <span><strong>Version:</strong> {topic.version}</span>
                                  <span><strong>Pages:</strong> {topic.source_page_start}-{topic.source_page_end}</span>
                                </div>
                                {topic.summary && (
                                  <p style={{ margin: '0 0 8px', fontSize: '13px', color: '#374151', lineHeight: '1.5' }}>{topic.summary}</p>
                                )}
                                {topic.guidelines && (
                                  <div>
                                    <div style={{ fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '4px' }}>Guidelines</div>
                                    <pre style={{
                                      margin: 0, padding: '12px', backgroundColor: 'white',
                                      border: '1px solid #E5E7EB', borderRadius: '6px', fontSize: '13px',
                                      lineHeight: '1.6', whiteSpace: 'pre-wrap', wordWrap: 'break-word',
                                      fontFamily: 'inherit', overflow: 'auto', maxHeight: '400px',
                                    }}>
                                      {topic.guidelines}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {book.chapters.length === 0 && (
        <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#F9FAFB', borderRadius: '12px', border: '2px dashed #D1D5DB' }}>
          <p style={{ color: '#6B7280' }}>No chapters defined. Edit the TOC to add chapters.</p>
        </div>
      )}

      {/* Page Detail Modal */}
      {selectedPage && (
        <div
          onClick={() => { setSelectedPage(null); setPageDetail(null); }}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: 'white', borderRadius: '12px', width: '90vw',
              maxWidth: '1100px', maxHeight: '85vh', overflow: 'hidden',
              display: 'flex', flexDirection: 'column',
            }}
          >
            {/* Modal Header */}
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #E5E7EB',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '16px' }}>
                  Page {selectedPage.pageNum}
                </h3>
                <span style={{ fontSize: '12px', color: '#6B7280' }}>
                  Chapter {selectedPage.chapter.chapter_number}: {selectedPage.chapter.chapter_title}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                {pageDetail && (
                  <span style={{
                    padding: '3px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: 600,
                    backgroundColor: pageDetail.ocr_status === 'completed' ? '#D1FAE5' : pageDetail.ocr_status === 'failed' ? '#FEE2E2' : '#FEF3C7',
                    color: pageDetail.ocr_status === 'completed' ? '#065F46' : pageDetail.ocr_status === 'failed' ? '#991B1B' : '#92400E',
                  }}>
                    OCR: {pageDetail.ocr_status}
                  </span>
                )}
                <button
                  onClick={() => { setSelectedPage(null); setPageDetail(null); }}
                  style={{
                    background: 'none', border: 'none', fontSize: '20px',
                    cursor: 'pointer', color: '#6B7280', padding: '4px 8px',
                  }}
                >
                  &times;
                </button>
              </div>
            </div>

            {/* Modal Body */}
            {pageDetailLoading ? (
              <div style={{ padding: '60px', textAlign: 'center', color: '#6B7280' }}>
                Loading page detail...
              </div>
            ) : pageDetail ? (
              <div style={{
                display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0,
              }}>
                {/* Left: Image */}
                <div style={{
                  flex: 1, overflow: 'auto', padding: '16px',
                  borderRight: '1px solid #E5E7EB', backgroundColor: '#F9FAFB',
                }}>
                  {pageDetail.image_url ? (
                    <img
                      src={pageDetail.image_url}
                      alt={`Page ${selectedPage.pageNum}`}
                      style={{ width: '100%', borderRadius: '6px' }}
                    />
                  ) : (
                    <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>
                      No image available
                    </div>
                  )}
                </div>

                {/* Right: OCR Text */}
                <div style={{
                  flex: 1, overflow: 'auto', padding: '16px',
                  display: 'flex', flexDirection: 'column',
                }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px', color: '#374151' }}>
                    OCR Text
                  </div>
                  {pageDetail.ocr_text ? (
                    <pre style={{
                      flex: 1, margin: 0, padding: '12px', backgroundColor: '#F9FAFB',
                      border: '1px solid #E5E7EB', borderRadius: '6px', fontSize: '13px',
                      lineHeight: '1.6', whiteSpace: 'pre-wrap', wordWrap: 'break-word',
                      fontFamily: 'inherit', overflow: 'auto',
                    }}>
                      {pageDetail.ocr_text}
                    </pre>
                  ) : pageDetail.ocr_status === 'failed' ? (
                    <div style={{
                      padding: '16px', backgroundColor: '#FEE2E2', borderRadius: '6px',
                      color: '#991B1B', fontSize: '13px',
                    }}>
                      OCR failed: {pageDetail.ocr_error || 'Unknown error'}
                    </div>
                  ) : (
                    <div style={{ padding: '16px', textAlign: 'center', color: '#9CA3AF' }}>
                      No OCR text available
                    </div>
                  )}
                </div>
              </div>
            ) : null}

            {/* Modal Footer */}
            {pageDetail && (
              <div style={{
                padding: '12px 20px', borderTop: '1px solid #E5E7EB',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {/* Re-upload */}
                  <label style={{
                    backgroundColor: '#3B82F6', color: 'white', border: 'none',
                    padding: '8px 16px', borderRadius: '6px', cursor: reuploadingPage ? 'wait' : 'pointer',
                    fontSize: '13px', fontWeight: 600, opacity: reuploadingPage ? 0.6 : 1,
                  }}>
                    {reuploadingPage ? 'Re-uploading...' : 'Re-upload'}
                    <input
                      type="file"
                      accept="image/*"
                      style={{ display: 'none' }}
                      disabled={reuploadingPage}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file && selectedPage) {
                          handleReuploadPage(selectedPage.chapter, selectedPage.pageNum, file);
                        }
                        e.target.value = '';
                      }}
                    />
                  </label>

                  {/* Retry OCR */}
                  {pageDetail.ocr_status === 'failed' && (
                    <button
                      onClick={() => handleRetryOcr(selectedPage.chapter, selectedPage.pageNum)}
                      disabled={retryingOcr}
                      style={{
                        backgroundColor: '#F59E0B', color: 'white', border: 'none',
                        padding: '8px 16px', borderRadius: '6px', cursor: retryingOcr ? 'wait' : 'pointer',
                        fontSize: '13px', fontWeight: 600, opacity: retryingOcr ? 0.6 : 1,
                      }}
                    >
                      {retryingOcr ? 'Retrying...' : 'Retry OCR'}
                    </button>
                  )}
                </div>

                {/* Delete */}
                <button
                  onClick={() => handleDeletePage(selectedPage.chapter, selectedPage.pageNum)}
                  style={{
                    backgroundColor: '#FEE2E2', color: '#991B1B', border: 'none',
                    padding: '8px 16px', borderRadius: '6px', cursor: 'pointer',
                    fontSize: '13px', fontWeight: 600,
                  }}
                >
                  Delete Page
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default BookV2Detail;
