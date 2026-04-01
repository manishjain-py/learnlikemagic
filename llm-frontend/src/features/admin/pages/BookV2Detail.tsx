import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getBookV2, deleteBookV2, uploadPageV2, deletePageV2, getChapterPages,
  startProcessing, reprocessChapter, refinalizeChapter,
  getLatestJobV2, getChapterTopics, syncChapter, syncBook,
  getPageDetailV2, retryPageOcrV2, generateExplanations, getExplanationJobStatus,
  getExplanationStatus, getTopicExplanations, deleteExplanations,
  bulkOcrRetry, bulkOcrRerun,
  BookV2DetailResponse, ChapterResponseV2, PageResponseV2,
  ProcessingJobResponseV2, ChapterTopicResponseV2, PageDetailResponseV2,
  SyncResponseV2, TopicExplanationStatusV2, TopicExplanationsDetailResponseV2,
  ExplanationVariantV2,
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
  const [explanationJobs, setExplanationJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [explanationStatus, setExplanationStatus] = useState<Record<string, TopicExplanationStatusV2[]>>({});
  const [viewingExplanations, setViewingExplanations] = useState<TopicExplanationsDetailResponseV2 | null>(null);
  const [viewingExplanationsLoading, setViewingExplanationsLoading] = useState(false);
  const [topicExplJobs, setTopicExplJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const [ocrJobs, setOcrJobs] = useState<Record<string, ProcessingJobResponseV2>>({});
  const pollingRef = useRef<Record<string, NodeJS.Timeout>>({});
  const pollingDoneRef = useRef<Set<string>>(new Set());
  const explPollingRef = useRef<Record<string, NodeJS.Timeout>>({});
  const topicExplPollingRef = useRef<Record<string, NodeJS.Timeout>>({});
  const ocrPollingRef = useRef<Record<string, NodeJS.Timeout>>({});

  useEffect(() => {
    if (id) loadBook(true);
    return () => {
      Object.values(pollingRef.current).forEach(clearInterval);
      Object.values(explPollingRef.current).forEach(clearInterval);
      Object.values(topicExplPollingRef.current).forEach(clearInterval);
      Object.values(ocrPollingRef.current).forEach(clearInterval);
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
        // Auto-detect active OCR jobs
        if (['upload_in_progress'].includes(ch.status) && !ocrPollingRef.current[ch.id]) {
          getLatestJobV2(id!, ch.id, 'v2_ocr').then(job => {
            if (['pending', 'running'].includes(job.status)) {
              setOcrJobs(prev => ({ ...prev, [ch.id]: job }));
              startOcrPolling(ch.id);
            }
          }).catch(() => {});
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

  const startExplanationPolling = useCallback((chapterId: string) => {
    if (!id || explPollingRef.current[chapterId]) return;
    const poll = async () => {
      try {
        const job = await getExplanationJobStatus(id!, { chapterId });
        setExplanationJobs(prev => ({ ...prev, [chapterId]: job }));
        if (['completed', 'failed', 'completed_with_errors'].includes(job.status)) {
          clearInterval(explPollingRef.current[chapterId]);
          delete explPollingRef.current[chapterId];
          // Refresh explanation status after completion
          loadExplanationStatus(chapterId);
        }
      } catch { /* ignore polling errors */ }
    };
    poll();
    explPollingRef.current[chapterId] = setInterval(poll, POLL_INTERVAL);
  }, [id]);

  const startOcrPolling = useCallback((chapterId: string) => {
    if (!id || ocrPollingRef.current[chapterId]) return;
    const poll = async () => {
      try {
        const job = await getLatestJobV2(id!, chapterId, 'v2_ocr');
        setOcrJobs(prev => ({ ...prev, [chapterId]: job }));
        if (['completed', 'completed_with_errors', 'failed'].includes(job.status)) {
          clearInterval(ocrPollingRef.current[chapterId]);
          delete ocrPollingRef.current[chapterId];
          // Refresh pages and book after OCR completes
          try {
            const pagesResp = await getChapterPages(id!, chapterId);
            setChapterPages(prev => ({ ...prev, [chapterId]: pagesResp.pages }));
          } catch {}
          loadBook();
        }
      } catch { /* ignore polling errors */ }
    };
    poll();
    ocrPollingRef.current[chapterId] = setInterval(poll, POLL_INTERVAL);
  }, [id]);

  const startTopicExplPolling = useCallback((guidelineId: string, chapterId: string) => {
    if (!id || topicExplPollingRef.current[guidelineId]) return;
    const poll = async () => {
      try {
        const job = await getExplanationJobStatus(id!, { guidelineId });
        setTopicExplJobs(prev => ({ ...prev, [guidelineId]: job }));
        if (['completed', 'failed', 'completed_with_errors'].includes(job.status)) {
          clearInterval(topicExplPollingRef.current[guidelineId]);
          delete topicExplPollingRef.current[guidelineId];
          loadExplanationStatus(chapterId);
        }
      } catch { /* ignore polling errors */ }
    };
    poll();
    topicExplPollingRef.current[guidelineId] = setInterval(poll, POLL_INTERVAL);
  }, [id]);

  const loadExplanationStatus = useCallback(async (chapterId: string) => {
    if (!id) return;
    try {
      const status = await getExplanationStatus(id, chapterId);
      setExplanationStatus(prev => ({ ...prev, [chapterId]: status.topics }));
    } catch { /* ignore */ }
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
    if (ch.status === 'chapter_completed' && !explanationStatus[chId]) {
      loadExplanationStatus(chId);
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

  const handleGenerateExplanations = async (ch: ChapterResponseV2, force = false) => {
    if (!id) return;
    try {
      const job = await generateExplanations(id, { chapterId: ch.id, force });
      setExplanationJobs(prev => ({ ...prev, [ch.id]: job }));
      startExplanationPolling(ch.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Explanation generation failed');
    }
  };

  const handleGenerateTopicExplanation = async (guidelineId: string, chapterId: string, force = false) => {
    if (!id) return;
    try {
      const job = await generateExplanations(id, { guidelineId, force });
      setTopicExplJobs(prev => ({ ...prev, [guidelineId]: job }));
      startTopicExplPolling(guidelineId, chapterId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Topic explanation generation failed');
    }
  };

  const handleDeleteTopicExplanation = async (guidelineId: string, chapterId: string, topicTitle: string) => {
    if (!id) return;
    if (!confirm(`Delete all explanations for "${topicTitle}"?`)) return;
    try {
      await deleteExplanations(id, { guidelineId });
      loadExplanationStatus(chapterId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleViewExplanations = async (guidelineId: string) => {
    if (!id) return;
    try {
      setViewingExplanationsLoading(true);
      const detail = await getTopicExplanations(id, guidelineId);
      setViewingExplanations(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load explanations');
    } finally {
      setViewingExplanationsLoading(false);
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

  const handleBulkOcrRetry = async (ch: ChapterResponseV2) => {
    if (!id) return;
    try {
      const job = await bulkOcrRetry(id, ch.id);
      setOcrJobs(prev => ({ ...prev, [ch.id]: job }));
      startOcrPolling(ch.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start OCR');
    }
  };

  const handleBulkOcrRerun = async (ch: ChapterResponseV2) => {
    if (!id) return;
    if (!confirm(`Re-OCR all pages in "${ch.chapter_title}"? This will reset all existing OCR results.`)) return;
    try {
      const job = await bulkOcrRerun(id, ch.id);
      setOcrJobs(prev => ({ ...prev, [ch.id]: job }));
      startOcrPolling(ch.id);
      loadBook();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start re-OCR');
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
          const ocrJob = ocrJobs[ch.id];
          const pages = chapterPages[ch.id] || [];
          const topics = chapterTopics[ch.id] || [];
          const pagesNeedingOcr = pages.filter(p => p.ocr_status === 'pending' || p.ocr_status === 'failed');
          const ocrRunning = ocrJob && ['pending', 'running'].includes(ocrJob.status);
          const ocrDone = ocrJob && ['completed', 'completed_with_errors', 'failed'].includes(ocrJob.status);

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

              {/* OCR progress — always visible when OCR job is active */}
              {ocrRunning && (
                <div style={{ borderTop: '1px solid #E5E7EB', padding: '12px 20px', backgroundColor: '#F0FDFA' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <div style={{ fontWeight: 600, fontSize: '13px', color: '#0F766E' }}>
                      {ocrJob.current_item || 'Starting OCR...'}
                    </div>
                    {ocrJob.total_items ? (
                      <span style={{ fontSize: '12px', color: '#0D9488', fontWeight: 600 }}>
                        {ocrJob.completed_items}/{ocrJob.total_items} pages
                        {ocrJob.failed_items > 0 && <span style={{ color: '#DC2626' }}> ({ocrJob.failed_items} failed)</span>}
                      </span>
                    ) : null}
                  </div>
                  {ocrJob.total_items ? (
                    <div style={{ height: '6px', backgroundColor: '#CCFBF1', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', backgroundColor: '#14B8A6', borderRadius: '3px',
                        width: `${((ocrJob.completed_items + ocrJob.failed_items) / ocrJob.total_items) * 100}%`,
                        transition: 'width 0.5s ease',
                      }} />
                    </div>
                  ) : (
                    <div style={{ height: '6px', backgroundColor: '#CCFBF1', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', backgroundColor: '#14B8A6', borderRadius: '3px', width: '30%',
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

                  {/* OCR completion banner */}
                  {ocrDone && (
                    <div style={{
                      marginBottom: '12px',
                      backgroundColor: ocrJob.status === 'failed' ? '#FEE2E2' : ocrJob.status === 'completed_with_errors' ? '#FEF3C7' : '#F0FDFA',
                      color: ocrJob.status === 'failed' ? '#991B1B' : ocrJob.status === 'completed_with_errors' ? '#92400E' : '#0F766E',
                      padding: '10px 14px', borderRadius: '6px', fontSize: '13px',
                    }}>
                      <button onClick={() => setOcrJobs(prev => { const next = { ...prev }; delete next[ch.id]; return next; })} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit' }}>&times;</button>
                      {ocrJob.status === 'failed'
                        ? `OCR failed: ${ocrJob.error_message || 'Unknown error'}`
                        : `OCR complete: ${ocrJob.completed_items} succeeded, ${ocrJob.failed_items} failed`}
                    </div>
                  )}

                  {/* ── Pipeline Steps + Actions ── */}
                  {!(job && ['pending', 'running'].includes(job.status)) && !ocrRunning && (() => {
                    const hasPages = ch.uploaded_page_count > 0;
                    const ocrDone = hasPages && pages.length > 0 && pages.every(p => p.ocr_status === 'completed');
                    const topicsReady = ['chapter_completed', 'needs_review', 'chapter_finalizing'].includes(ch.status);
                    const completed = ch.status === 'chapter_completed';
                    const isFailed = ch.status === 'failed';

                    // Pipeline step indicators
                    const steps = [
                      { label: 'OCR', done: ocrDone, active: hasPages && !ocrDone },
                      { label: 'Topics', done: topicsReady, active: ocrDone && !topicsReady && !isFailed },
                      { label: 'Sync', done: !!(syncResult[ch.id]), active: completed },
                      { label: 'Explanations', done: (explanationStatus[ch.id]?.length ?? 0) > 0 && explanationStatus[ch.id]?.every(t => t.variant_count > 0), active: completed },
                      { label: 'Visuals', done: false, active: completed },
                    ];

                    return (
                      <div style={{ marginTop: '8px' }}>
                        {/* Step indicators */}
                        {hasPages && (
                          <div style={{ display: 'flex', gap: '4px', marginBottom: '10px', alignItems: 'center' }}>
                            {steps.map((s, i) => (
                              <React.Fragment key={s.label}>
                                {i > 0 && <span style={{ color: '#D1D5DB', fontSize: '10px' }}>&rarr;</span>}
                                <span style={{
                                  fontSize: '11px', fontWeight: 600, padding: '2px 8px', borderRadius: '10px',
                                  backgroundColor: s.done ? '#D1FAE5' : s.active ? '#EDE9FE' : '#F3F4F6',
                                  color: s.done ? '#065F46' : s.active ? '#5B21B6' : '#9CA3AF',
                                }}>{s.done ? '\u2713 ' : ''}{s.label}</span>
                              </React.Fragment>
                            ))}
                          </div>
                        )}

                        {/* Next action + manage links */}
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                          {/* Primary next action */}
                          {hasPages && !ocrDone && pagesNeedingOcr.length > 0 && (
                            <button onClick={() => handleBulkOcrRetry(ch)} style={{ backgroundColor: '#14B8A6', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                              Run OCR ({pagesNeedingOcr.length} pages)
                            </button>
                          )}
                          {ch.status === 'upload_complete' && ocrDone && (
                            <button onClick={() => handleStartProcessing(ch)} style={{ backgroundColor: '#7C3AED', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                              Extract Topics
                            </button>
                          )}
                          {isFailed && (
                            <>
                              <button onClick={() => handleStartProcessing(ch)} style={{ backgroundColor: '#F59E0B', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                                Resume
                              </button>
                              <button onClick={() => handleReprocess(ch)} style={{ backgroundColor: '#EF4444', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                                Reprocess
                              </button>
                            </>
                          )}
                          {completed && (
                            <button onClick={() => handleSyncChapter(ch)} disabled={syncingChapterId === ch.id} style={{ backgroundColor: '#10B981', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: syncingChapterId === ch.id ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600, opacity: syncingChapterId === ch.id ? 0.6 : 1 }}>
                              {syncingChapterId === ch.id ? 'Syncing...' : 'Sync to DB'}
                            </button>
                          )}

                          {/* Separator before manage links */}
                          {hasPages && <span style={{ color: '#D1D5DB', margin: '0 4px' }}>|</span>}

                          {/* Manage links — only show for completed steps */}
                          {hasPages && (
                            <button onClick={() => navigate(`/admin/books-v2/${id}/ocr/${ch.id}`)} style={manageLinkStyle}>OCR</button>
                          )}
                          {hasPages && (
                            <button onClick={() => navigate(`/admin/books-v2/${id}/topics/${ch.id}`)} style={manageLinkStyle}>Topics</button>
                          )}
                          {completed && (
                            <>
                              <button onClick={() => navigate(`/admin/books-v2/${id}/guidelines/${ch.id}`)} style={manageLinkStyle}>Guidelines</button>
                              <button onClick={() => navigate(`/admin/books-v2/${id}/explanations/${ch.id}`)} style={manageLinkStyle}>Explanations</button>
                              <button onClick={() => navigate(`/admin/books-v2/${id}/visuals/${ch.id}`)} style={manageLinkStyle}>Visuals</button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Explanation generation progress/result banner */}
                  {explanationJobs[ch.id] && (() => {
                    const ej = explanationJobs[ch.id];
                    const isRunning = ['pending', 'running'].includes(ej.status);
                    const isDone = ['completed', 'completed_with_errors', 'failed'].includes(ej.status);
                    const detail = ej.progress_detail as { generated?: number; skipped?: number; failed?: number; errors?: string[] } | undefined;
                    if (isRunning) return (
                      <div style={{ marginTop: '12px', backgroundColor: '#EDE9FE', color: '#5B21B6', padding: '10px 14px', borderRadius: '6px', fontSize: '13px' }}>
                        Generating explanations{ej.current_item ? `: ${ej.current_item}` : '...'}
                        {ej.total_items ? ` (${ej.completed_items + ej.failed_items}/${ej.total_items})` : ''}
                      </div>
                    );
                    if (isDone) {
                      const hasErrors = ej.status === 'failed' || (detail?.errors && detail.errors.length > 0);
                      return (
                        <div style={{
                          marginTop: '12px',
                          backgroundColor: hasErrors ? '#FEF3C7' : '#EDE9FE',
                          color: hasErrors ? '#92400E' : '#5B21B6',
                          padding: '10px 14px', borderRadius: '6px', fontSize: '13px',
                        }}>
                          <button onClick={() => setExplanationJobs(prev => { const next = { ...prev }; delete next[ch.id]; return next; })} style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit' }}>&times;</button>
                          {ej.status === 'failed' && ej.error_message
                            ? `Explanation generation failed: ${ej.error_message}`
                            : `Explanations: ${detail?.generated ?? ej.completed_items} generated, ${detail?.skipped ?? 0} skipped, ${detail?.failed ?? ej.failed_items} failed.`}
                          {detail?.errors && detail.errors.length > 0 && (
                            <ul style={{ margin: '4px 0 0', paddingLeft: '20px' }}>
                              {detail.errors.map((e, i) => <li key={i}>{e}</li>)}
                            </ul>
                          )}
                        </div>
                      );
                    }
                    return null;
                  })()}

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
                        // Look up explanation status for this topic
                        const explStatus = (explanationStatus[ch.id] || []).find(s => s.topic_key === topic.topic_key);
                        const variantCount = explStatus?.variant_count ?? 0;
                        const guidelineId = explStatus?.guideline_id;
                        const topicJob = guidelineId ? topicExplJobs[guidelineId] : undefined;
                        const topicJobRunning = topicJob && ['pending', 'running'].includes(topicJob.status);
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
                                {variantCount > 0 ? (
                                  <span style={{ backgroundColor: '#DBEAFE', color: '#1D4ED8', padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 600 }}>
                                    {variantCount} variant{variantCount !== 1 ? 's' : ''}
                                  </span>
                                ) : explStatus ? (
                                  <span style={{ backgroundColor: '#F3F4F6', color: '#6B7280', padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 600 }}>
                                    No explanations
                                  </span>
                                ) : null}
                                {topicJobRunning && (
                                  <span style={{ backgroundColor: '#EDE9FE', color: '#5B21B6', padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 600 }}>
                                    Generating...
                                  </span>
                                )}
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

                                {/* Topic-level explanation actions */}
                                {guidelineId && (
                                  <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                                    {variantCount > 0 && (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleViewExplanations(guidelineId); }}
                                        style={{ backgroundColor: '#3B82F6', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '5px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                                      >
                                        View Explanations
                                      </button>
                                    )}
                                    {variantCount === 0 ? (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleGenerateTopicExplanation(guidelineId, ch.id); }}
                                        disabled={!!topicJobRunning}
                                        style={{ backgroundColor: '#8B5CF6', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '5px', cursor: topicJobRunning ? 'wait' : 'pointer', fontSize: '12px', fontWeight: 600, opacity: topicJobRunning ? 0.6 : 1 }}
                                      >
                                        Generate Explanations
                                      </button>
                                    ) : (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleGenerateTopicExplanation(guidelineId, ch.id, true); }}
                                        disabled={!!topicJobRunning}
                                        style={{ backgroundColor: '#7C3AED', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '5px', cursor: topicJobRunning ? 'wait' : 'pointer', fontSize: '12px', fontWeight: 600, opacity: topicJobRunning ? 0.6 : 1 }}
                                      >
                                        Regenerate
                                      </button>
                                    )}
                                    {variantCount > 0 && (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleDeleteTopicExplanation(guidelineId, ch.id, topic.topic_title); }}
                                        style={{ backgroundColor: '#FEE2E2', color: '#991B1B', border: 'none', padding: '6px 12px', borderRadius: '5px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                                      >
                                        Delete Explanations
                                      </button>
                                    )}
                                    {/* Topic-level job status */}
                                    {topicJob && (() => {
                                      const tj = topicJob;
                                      if (topicJobRunning) return (
                                        <span style={{ fontSize: '12px', color: '#5B21B6' }}>
                                          Generating{tj.current_item ? `: ${tj.current_item}` : '...'}
                                        </span>
                                      );
                                      if (['completed', 'completed_with_errors', 'failed'].includes(tj.status)) {
                                        const td = tj.progress_detail as { generated?: number; failed?: number; errors?: string[] } | undefined;
                                        return (
                                          <span style={{ fontSize: '12px', color: tj.status === 'failed' ? '#991B1B' : '#065F46' }}>
                                            {tj.status === 'failed' ? `Failed: ${tj.error_message}` : `Done: ${td?.generated ?? tj.completed_items} generated`}
                                            <button onClick={() => setTopicExplJobs(prev => { const next = { ...prev }; delete next[guidelineId]; return next; })} style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold', color: 'inherit', marginLeft: '4px' }}>&times;</button>
                                          </span>
                                        );
                                      }
                                      return null;
                                    })()}
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

      {/* Explanations Viewer Modal */}
      {viewingExplanations && (
        <div
          onClick={() => setViewingExplanations(null)}
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
              maxWidth: '1000px', maxHeight: '85vh', overflow: 'hidden',
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
                  Explanations: {viewingExplanations.topic_title}
                </h3>
                <span style={{ fontSize: '12px', color: '#6B7280' }}>
                  {viewingExplanations.variants.length} variant{viewingExplanations.variants.length !== 1 ? 's' : ''}
                  {viewingExplanations.topic_key ? ` — ${viewingExplanations.topic_key}` : ''}
                </span>
              </div>
              <button
                onClick={() => setViewingExplanations(null)}
                style={{ background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer', color: '#6B7280', padding: '4px 8px' }}
              >
                &times;
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ flex: 1, overflow: 'auto', padding: '16px' }}>
              {viewingExplanations.variants.length === 0 ? (
                <div style={{ padding: '40px', textAlign: 'center', color: '#9CA3AF' }}>
                  No explanations generated yet.
                </div>
              ) : (
                viewingExplanations.variants.map((variant) => (
                  <VariantSection key={variant.id} variant={variant} />
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

/* ─── Explanation Variant Section Component ─── */
const VariantSection: React.FC<{ variant: ExplanationVariantV2 }> = ({ variant }) => {
  const [expanded, setExpanded] = useState(true);
  const summary = variant.summary_json as { card_titles?: string[]; key_analogies?: string[]; key_examples?: string[]; approach_label?: string } | null;
  return (
    <div style={{ marginBottom: '16px', border: '1px solid #E5E7EB', borderRadius: '8px', overflow: 'hidden' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '12px 16px', backgroundColor: '#F9FAFB', cursor: 'pointer',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{expanded ? '▼' : '▶'}</span>
          <span style={{ fontWeight: 700, fontSize: '14px' }}>
            Variant {variant.variant_key}: {variant.variant_label}
          </span>
          <span style={{ fontSize: '12px', color: '#6B7280' }}>
            ({variant.cards_json.length} cards)
          </span>
        </div>
        <div style={{ display: 'flex', gap: '12px', fontSize: '11px', color: '#9CA3AF' }}>
          {variant.generator_model && <span>Model: {variant.generator_model}</span>}
          {variant.created_at && <span>{new Date(variant.created_at).toLocaleDateString()}</span>}
        </div>
      </div>
      {expanded && (
        <div style={{ padding: '12px 16px' }}>
          {/* Summary */}
          {summary && (
            <div style={{ marginBottom: '12px', padding: '10px', backgroundColor: '#F0F9FF', borderRadius: '6px', fontSize: '12px', color: '#1E40AF' }}>
              {summary.approach_label && <div><strong>Approach:</strong> {summary.approach_label}</div>}
              {summary.key_analogies && summary.key_analogies.length > 0 && (
                <div><strong>Key Analogies:</strong> {summary.key_analogies.join(', ')}</div>
              )}
              {summary.key_examples && summary.key_examples.length > 0 && (
                <div><strong>Key Examples:</strong> {summary.key_examples.join(', ')}</div>
              )}
            </div>
          )}
          {/* Cards */}
          {variant.cards_json.map((card, ci) => (
            <div key={ci} style={{
              marginBottom: '8px', padding: '10px 14px',
              border: '1px solid #E5E7EB', borderRadius: '6px',
              backgroundColor: card.card_type === 'visual' ? '#FFFBEB' : 'white',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontWeight: 600, fontSize: '13px' }}>
                  {card.card_idx}. {card.title}
                </span>
                <span style={{
                  fontSize: '10px', fontWeight: 600, padding: '2px 6px', borderRadius: '8px',
                  backgroundColor:
                    card.card_type === 'concept' ? '#EDE9FE' :
                    card.card_type === 'example' ? '#DBEAFE' :
                    card.card_type === 'visual' ? '#FEF3C7' :
                    card.card_type === 'analogy' ? '#D1FAE5' :
                    card.card_type === 'summary' ? '#F3F4F6' : '#F3F4F6',
                  color:
                    card.card_type === 'concept' ? '#5B21B6' :
                    card.card_type === 'example' ? '#1D4ED8' :
                    card.card_type === 'visual' ? '#92400E' :
                    card.card_type === 'analogy' ? '#065F46' :
                    '#374151',
                }}>
                  {card.card_type}
                </span>
              </div>
              <div style={{ fontSize: '13px', color: '#374151', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
                {card.content}
              </div>
              {card.visual && (
                <pre style={{
                  marginTop: '8px', padding: '10px', backgroundColor: '#F9FAFB',
                  border: '1px solid #E5E7EB', borderRadius: '4px', fontSize: '12px',
                  lineHeight: '1.4', overflow: 'auto', fontFamily: 'monospace',
                }}>
                  {card.visual}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const manageLinkStyle: React.CSSProperties = {
  background: 'none', border: '1px solid #D1D5DB', color: '#374151',
  padding: '4px 10px', borderRadius: '4px', cursor: 'pointer',
  fontSize: '11px', fontWeight: 500,
};

export default BookV2Detail;
