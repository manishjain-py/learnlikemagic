/**
 * TopicPipelineDashboard — 6-stage admin hub for one topic.
 *
 * Phase 1: read-only. Status ladder + deep links to per-stage admin pages.
 * Phase 2: wires the super-button (Run entire pipeline) + Quality selector.
 * Phase 3: prev/next topic nav, inline Retry buttons, polish.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTopicPipeline } from '../hooks/useTopicPipeline';
import StageLadderRow from '../components/StageLadderRow';
import QualitySelector from '../components/QualitySelector';
import {
  ApiError,
  getChapterPipelineSummary,
  generateExplanations,
  generateVisuals,
  generateCheckIns,
  generatePracticeBanks,
  generateAudio,
  generateAudioReview,
  runTopicPipeline,
  type ChapterPipelineSummary,
  type QualityLevel,
  type StageId,
} from '../api/adminApiV2';

const STAGE_ORDER: StageId[] = [
  'explanations',
  'visuals',
  'check_ins',
  'practice_bank',
  'audio_review',
  'audio_synthesis',
];

const TopicPipelineDashboard: React.FC = () => {
  const { bookId, chapterId, topicKey } = useParams<{
    bookId: string;
    chapterId: string;
    topicKey: string;
  }>();
  const navigate = useNavigate();

  const { data, error, loading, refresh } = useTopicPipeline(
    bookId || '',
    chapterId || '',
    topicKey || '',
  );

  const [qualityOpen, setQualityOpen] = useState(false);
  const [launchingRun, setLaunchingRun] = useState(false);
  const [force, setForce] = useState(false);
  const [lastRunInfo, setLastRunInfo] = useState<{
    pipelineRunId: string;
    stagesToRun: StageId[];
    message?: string;
  } | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [chapterSummary, setChapterSummary] = useState<ChapterPipelineSummary | null>(null);

  useEffect(() => {
    if (!bookId || !chapterId) return;
    let alive = true;
    getChapterPipelineSummary(bookId, chapterId)
      .then((summary) => {
        if (alive) setChapterSummary(summary);
      })
      .catch(() => {
        /* ignore — prev/next nav is a convenience, not required */
      });
    return () => {
      alive = false;
    };
  }, [bookId, chapterId]);

  const { prevTopicKey, nextTopicKey } = useMemo(() => {
    if (!chapterSummary || !topicKey) return { prevTopicKey: null, nextTopicKey: null };
    const keys = chapterSummary.topics.map((t) => t.topic_key);
    const idx = keys.indexOf(topicKey);
    if (idx < 0) return { prevTopicKey: null, nextTopicKey: null };
    return {
      prevTopicKey: idx > 0 ? keys[idx - 1] : null,
      nextTopicKey: idx < keys.length - 1 ? keys[idx + 1] : null,
    };
  }, [chapterSummary, topicKey]);

  const orderedStages = useMemo(() => {
    if (!data) return [];
    const byId = new Map(data.stages.map((s) => [s.stage_id, s]));
    return STAGE_ORDER.map((id) => byId.get(id)).filter(
      (s): s is NonNullable<typeof s> => Boolean(s),
    );
  }, [data]);

  const anyRunning = useMemo(
    () => orderedStages.some((s) => s.state === 'running'),
    [orderedStages],
  );

  if (!bookId || !chapterId || !topicKey) {
    return (
      <div style={{ padding: 24, color: '#991B1B' }}>
        Missing book/chapter/topic in URL.
      </div>
    );
  }

  const handleSuperRun = async (quality: QualityLevel) => {
    setQualityOpen(false);
    setRunError(null);
    setLaunchingRun(true);
    try {
      const resp = await runTopicPipeline(bookId!, chapterId!, topicKey!, {
        quality_level: quality,
        force,
      });
      setLastRunInfo({
        pipelineRunId: resp.pipeline_run_id,
        stagesToRun: resp.stages_to_run,
        message: resp.message,
      });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setRunError(typeof err.detail === 'string' ? err.detail : err.message);
      } else {
        setRunError(err instanceof Error ? err.message : 'Failed to launch pipeline');
      }
    } finally {
      setLaunchingRun(false);
    }
  };

  const handleStageAction = async (stageId: StageId, action: 'retry' | 'regenerate' | 'run') => {
    if (!bookId || !data) return;
    const guidelineId = data.guideline_id;
    const shouldForce = action === 'regenerate' || action === 'retry';
    try {
      if (stageId === 'explanations') {
        await generateExplanations(bookId, { guidelineId, force: shouldForce });
      } else if (stageId === 'visuals') {
        await generateVisuals(bookId, { guidelineId, force: shouldForce });
      } else if (stageId === 'check_ins') {
        await generateCheckIns(bookId, { guidelineId, force: shouldForce });
      } else if (stageId === 'practice_bank') {
        await generatePracticeBanks(bookId, { guidelineId, force: shouldForce });
      } else if (stageId === 'audio_review') {
        await generateAudioReview(bookId, { guidelineId });
      } else if (stageId === 'audio_synthesis') {
        await generateAudio(bookId, { guidelineId });
      }
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && stageId === 'audio_synthesis') {
        const detail = err.detail as { message?: string; requires_confirmation?: boolean };
        if (detail?.requires_confirmation && confirm(detail.message || 'Proceed without audio review?')) {
          try {
            await generateAudio(bookId, { guidelineId, confirmSkipReview: true });
            await refresh();
            return;
          } catch (err2) {
            setRunError(err2 instanceof Error ? err2.message : `Failed to ${action} ${stageId}`);
            return;
          }
        }
      }
      setRunError(err instanceof Error ? err.message : `Failed to ${action} ${stageId}`);
    }
  };

  return (
    <div style={{ maxWidth: 1024, margin: '0 auto', padding: '24px 20px' }}>
      {/* Sticky header */}
      <div
        style={{
          position: 'sticky',
          top: 56,
          zIndex: 10,
          backgroundColor: 'white',
          borderBottom: '1px solid #E5E7EB',
          padding: '14px 0 12px',
          marginBottom: 16,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#6B7280', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => navigate(`/admin/books-v2/${bookId}`)}
              style={{
                background: 'none',
                border: 'none',
                color: '#4F46E5',
                cursor: 'pointer',
                padding: 0,
                fontSize: 13,
              }}
            >
              ← Back to book
            </button>
            <span style={{ color: '#9CA3AF' }}>/</span>
            <span>Topic Pipeline</span>
            <button
              type="button"
              onClick={() => prevTopicKey && navigate(`/admin/books-v2/${bookId}/pipeline/${chapterId}/${encodeURIComponent(prevTopicKey)}`)}
              disabled={!prevTopicKey}
              style={{
                padding: '3px 10px',
                fontSize: 12,
                color: prevTopicKey ? '#374151' : '#D1D5DB',
                backgroundColor: prevTopicKey ? '#F3F4F6' : 'transparent',
                border: `1px solid ${prevTopicKey ? '#D1D5DB' : '#E5E7EB'}`,
                borderRadius: 10,
                cursor: prevTopicKey ? 'pointer' : 'not-allowed',
                marginLeft: 8,
              }}
            >
              ← Prev
            </button>
            <button
              type="button"
              onClick={() => nextTopicKey && navigate(`/admin/books-v2/${bookId}/pipeline/${chapterId}/${encodeURIComponent(nextTopicKey)}`)}
              disabled={!nextTopicKey}
              style={{
                padding: '3px 10px',
                fontSize: 12,
                color: nextTopicKey ? '#374151' : '#D1D5DB',
                backgroundColor: nextTopicKey ? '#F3F4F6' : 'transparent',
                border: `1px solid ${nextTopicKey ? '#D1D5DB' : '#E5E7EB'}`,
                borderRadius: 10,
                cursor: nextTopicKey ? 'pointer' : 'not-allowed',
              }}
            >
              Next →
            </button>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', position: 'relative' }}>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              style={{
                padding: '6px 12px',
                fontSize: 13,
                color: '#374151',
                backgroundColor: '#F3F4F6',
                border: '1px solid #D1D5DB',
                borderRadius: 4,
                cursor: 'pointer',
              }}
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => setQualityOpen((v) => !v)}
              disabled={launchingRun || anyRunning}
              title={anyRunning ? 'Wait for the current run to settle' : 'Run entire pipeline'}
              style={{
                padding: '6px 14px',
                fontSize: 13,
                fontWeight: 600,
                color: 'white',
                backgroundColor: launchingRun || anyRunning ? '#9CA3AF' : '#4F46E5',
                border: 'none',
                borderRadius: 4,
                cursor: launchingRun || anyRunning ? 'not-allowed' : 'pointer',
              }}
            >
              {launchingRun ? 'Starting…' : '▶ Run entire pipeline'}
            </button>

            <QualitySelector
              open={qualityOpen}
              onClose={() => setQualityOpen(false)}
              onPick={handleSuperRun}
              force={force}
              onForceChange={setForce}
            />
          </div>
        </div>

        <div style={{ marginTop: 8 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            {data?.topic_title || topicKey}
          </h1>
          <div style={{ fontSize: 13, color: '#6B7280', marginTop: 2 }}>
            topic_key: <code>{topicKey}</code>
          </div>
        </div>
      </div>

      {(error || runError) && (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#FEF2F2',
            border: '1px solid #FCA5A5',
            borderRadius: 6,
            color: '#991B1B',
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {error ? `Failed to load pipeline status: ${error.message}` : runError}
        </div>
      )}

      {lastRunInfo && (
        <div
          style={{
            padding: '10px 14px',
            backgroundColor: '#ECFDF5',
            border: '1px solid #6EE7B7',
            borderRadius: 6,
            color: '#065F46',
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {lastRunInfo.message ||
            `Launched pipeline ${lastRunInfo.pipelineRunId.slice(0, 8)}. ` +
              `Running: ${lastRunInfo.stagesToRun.join(', ') || 'nothing'}.`}
        </div>
      )}

      {loading && !data && (
        <div style={{ padding: '24px 0', color: '#6B7280', fontSize: 13 }}>
          Loading pipeline status…
        </div>
      )}

      {data && (
        <div
          style={{
            backgroundColor: 'white',
            border: '1px solid #E5E7EB',
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          {orderedStages.map((stage) => (
            <StageLadderRow
              key={stage.stage_id}
              stage={stage}
              bookId={bookId}
              chapterId={chapterId}
              onRetry={(sid) => handleStageAction(sid, 'retry')}
              onRegenerate={(sid) => handleStageAction(sid, 'regenerate')}
              onRun={(sid) => handleStageAction(sid, 'run')}
              onRunSkipReview={() => handleStageAction('audio_synthesis', 'run')}
              disableActions={launchingRun}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default TopicPipelineDashboard;
