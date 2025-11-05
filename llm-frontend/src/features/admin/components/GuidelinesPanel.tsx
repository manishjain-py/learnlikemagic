/**
 * Guidelines Panel Component
 *
 * Displays generated guidelines for a book with options to:
 * - Generate guidelines
 * - View all subtopics
 * - Review individual subtopics
 * - Approve/reject guidelines
 */

import React, { useState, useEffect } from 'react';
import {
  generateGuidelines,
  getGuidelines,
  approveGuidelines,
  rejectGuidelines,
} from '../api/adminApi';
import {
  GuidelineSubtopic,
  GenerateGuidelinesRequest,
  GenerateGuidelinesResponse,
} from '../types';

interface GuidelinesPanelProps {
  bookId: string;
  totalPages: number;
}

export const GuidelinesPanel: React.FC<GuidelinesPanelProps> = ({
  bookId,
  totalPages,
}) => {
  const [guidelines, setGuidelines] = useState<GuidelineSubtopic[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSubtopic, setSelectedSubtopic] = useState<GuidelineSubtopic | null>(null);
  const [generationStats, setGenerationStats] = useState<GenerateGuidelinesResponse | null>(null);

  // Load guidelines on mount
  useEffect(() => {
    loadGuidelines();
  }, [bookId]);

  const loadGuidelines = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await getGuidelines(bookId);
      setGuidelines(response.guidelines);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load guidelines');
      setGuidelines([]);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateGuidelines = async () => {
    setGenerating(true);
    setError(null);
    setGenerationStats(null);

    const request: GenerateGuidelinesRequest = {
      start_page: 1,
      end_page: totalPages,
      auto_sync_to_db: false, // User will approve manually
    };

    try {
      const stats = await generateGuidelines(bookId, request);
      setGenerationStats(stats);

      // Reload guidelines
      await loadGuidelines();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate guidelines');
    } finally {
      setGenerating(false);
    }
  };

  const handleApproveGuidelines = async () => {
    if (!window.confirm('Approve all final guidelines and sync to database?')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await approveGuidelines(bookId);
      alert(`Successfully synced ${response.synced_count} guidelines to database`);

      // Reload guidelines
      await loadGuidelines();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve guidelines');
    } finally {
      setLoading(false);
    }
  };

  const handleRejectGuidelines = async () => {
    if (!window.confirm('Delete all guidelines? This cannot be undone.')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await rejectGuidelines(bookId);
      setGuidelines([]);
      setSelectedSubtopic(null);
      setGenerationStats(null);
      alert('Guidelines deleted successfully');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject guidelines');
    } finally {
      setLoading(false);
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case 'final':
        return 'bg-green-100 text-green-800';
      case 'needs_review':
        return 'bg-red-100 text-red-800';
      case 'stable':
        return 'bg-blue-100 text-blue-800';
      case 'open':
        return 'bg-yellow-100 text-yellow-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getQualityScoreColor = (score: number | null) => {
    if (score === null) return 'text-gray-500';
    if (score >= 0.9) return 'text-green-600';
    if (score >= 0.7) return 'text-blue-600';
    if (score >= 0.5) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold">Teaching Guidelines</h2>
        <div className="flex gap-2">
          {guidelines.length === 0 ? (
            <button
              onClick={handleGenerateGuidelines}
              disabled={generating || totalPages === 0}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400"
            >
              {generating ? 'Generating...' : 'Generate Guidelines'}
            </button>
          ) : (
            <>
              <button
                onClick={handleApproveGuidelines}
                disabled={loading}
                className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:bg-gray-400"
              >
                Approve & Sync to DB
              </button>
              <button
                onClick={handleRejectGuidelines}
                disabled={loading}
                className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:bg-gray-400"
              >
                Reject & Delete
              </button>
              <button
                onClick={handleGenerateGuidelines}
                disabled={generating}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400"
              >
                Regenerate
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mb-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded">
          {error}
        </div>
      )}

      {/* Generation stats */}
      {generationStats && (
        <div className="mb-4 p-4 bg-blue-100 border border-blue-400 text-blue-700 rounded">
          <h3 className="font-bold mb-2">Generation Complete</h3>
          <p>Pages processed: {generationStats.pages_processed}</p>
          <p>Subtopics created: {generationStats.subtopics_created}</p>
          {generationStats.subtopics_merged !== undefined && generationStats.subtopics_merged > 0 && (
            <p>Subtopics merged: {generationStats.subtopics_merged}</p>
          )}
          <p>Subtopics finalized: {generationStats.subtopics_finalized}</p>
          {generationStats.duplicates_merged !== undefined && generationStats.duplicates_merged > 0 && (
            <p>Duplicates merged: {generationStats.duplicates_merged}</p>
          )}
          {generationStats.errors.length > 0 && (
            <div className="mt-2">
              <p className="font-semibold">Errors:</p>
              <ul className="list-disc list-inside">
                {generationStats.errors.map((err, idx) => (
                  <li key={idx}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Loading state */}
      {loading && guidelines.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          Loading guidelines...
        </div>
      )}

      {/* Empty state */}
      {!loading && !generating && guidelines.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          <p className="mb-4">No guidelines generated yet</p>
          <p className="text-sm">
            Click "Generate Guidelines" to extract teaching guidelines from all pages
          </p>
        </div>
      )}

      {/* Guidelines list */}
      {guidelines.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Subtopics list */}
          <div className="space-y-2 max-h-[600px] overflow-y-auto">
            <h3 className="font-semibold text-lg mb-4">
              Subtopics ({guidelines.length})
            </h3>
            {guidelines.map((guideline) => (
              <div
                key={`${guideline.topic_key}-${guideline.subtopic_key}`}
                onClick={() => setSelectedSubtopic(guideline)}
                className={`p-4 border rounded cursor-pointer hover:bg-gray-50 ${
                  selectedSubtopic?.subtopic_key === guideline.subtopic_key
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200'
                }`}
              >
                <div className="flex justify-between items-start mb-2">
                  <h4 className="font-semibold">{guideline.subtopic_title}</h4>
                  <span
                    className={`px-2 py-1 text-xs rounded ${getStatusBadgeColor(
                      guideline.status
                    )}`}
                  >
                    {guideline.status}
                  </span>
                </div>
                <p className="text-sm text-gray-600">{guideline.topic_title}</p>
                <div className="flex justify-between items-center mt-2 text-xs text-gray-500">
                  <span>Pages {guideline.source_page_start}-{guideline.source_page_end}</span>
                  {guideline.quality_score !== null && (
                    <span className={getQualityScoreColor(guideline.quality_score)}>
                      Quality: {(guideline.quality_score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Right: Subtopic details */}
          <div className="border rounded p-6 max-h-[600px] overflow-y-auto">
            {selectedSubtopic ? (
              <div>
                <h3 className="text-xl font-bold mb-4">
                  {selectedSubtopic.subtopic_title}
                </h3>

                {/* V2: Single Guidelines Field (Primary Display) */}
                {selectedSubtopic.guidelines && (
                  <div className="mb-6">
                    <h4 className="font-semibold text-sm text-gray-700 mb-2">
                      Teaching Guidelines
                    </h4>
                    <div className="p-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg">
                      <div className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">
                        {selectedSubtopic.guidelines}
                      </div>
                    </div>
                  </div>
                )}

                {/* V1: Structured Fields (Backward Compatibility) */}
                {!selectedSubtopic.guidelines && (
                  <>
                    {/* Comprehensive Description */}
                    {selectedSubtopic.description && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Overview
                        </h4>
                        <div className="p-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg">
                          <p className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">
                            {selectedSubtopic.description}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Teaching Description */}
                    {selectedSubtopic.teaching_description && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Teaching Instructions (Quick Reference)
                        </h4>
                        <div className="p-3 bg-yellow-50 border border-yellow-200 rounded whitespace-pre-wrap text-sm">
                          {selectedSubtopic.teaching_description}
                        </div>
                      </div>
                    )}

                    {/* Objectives */}
                    {selectedSubtopic.objectives && selectedSubtopic.objectives.length > 0 && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Objectives ({selectedSubtopic.objectives.length})
                        </h4>
                        <ul className="list-disc list-inside space-y-1">
                          {selectedSubtopic.objectives.map((obj, idx) => (
                            <li key={idx} className="text-sm">{obj}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Examples */}
                    {selectedSubtopic.examples && selectedSubtopic.examples.length > 0 && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Examples ({selectedSubtopic.examples.length})
                        </h4>
                        <ul className="list-disc list-inside space-y-1">
                          {selectedSubtopic.examples.slice(0, 5).map((ex, idx) => (
                            <li key={idx} className="text-sm">{ex}</li>
                          ))}
                          {selectedSubtopic.examples.length > 5 && (
                            <li className="text-sm text-gray-500">
                              ...and {selectedSubtopic.examples.length - 5} more
                            </li>
                          )}
                        </ul>
                      </div>
                    )}

                    {/* Misconceptions */}
                    {selectedSubtopic.misconceptions && selectedSubtopic.misconceptions.length > 0 && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Misconceptions ({selectedSubtopic.misconceptions.length})
                        </h4>
                        <ul className="list-disc list-inside space-y-1">
                          {selectedSubtopic.misconceptions.map((m, idx) => (
                            <li key={idx} className="text-sm text-red-700">{m}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Assessments */}
                    {selectedSubtopic.assessments && selectedSubtopic.assessments.length > 0 && (
                      <div className="mb-6">
                        <h4 className="font-semibold text-sm text-gray-700 mb-2">
                          Assessments ({selectedSubtopic.assessments.length})
                        </h4>
                        <div className="space-y-2">
                          {selectedSubtopic.assessments.slice(0, 3).map((a, idx) => (
                            <div key={idx} className="p-2 bg-gray-50 rounded text-sm">
                              <div className="flex justify-between items-center mb-1">
                                <span className="font-semibold">{a.prompt}</span>
                                <span className={`px-2 py-0.5 text-xs rounded ${
                                  a.level === 'advanced' ? 'bg-red-100 text-red-800' :
                                  a.level === 'proficient' ? 'bg-blue-100 text-blue-800' :
                                  'bg-green-100 text-green-800'
                                }`}>
                                  {a.level}
                                </span>
                              </div>
                              <p className="text-gray-600">Answer: {a.answer}</p>
                            </div>
                          ))}
                          {selectedSubtopic.assessments.length > 3 && (
                            <p className="text-sm text-gray-500">
                              ...and {selectedSubtopic.assessments.length - 3} more
                            </p>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* Metadata */}
                <div className="mt-6 pt-4 border-t text-xs text-gray-500">
                  <p>Source Pages: {selectedSubtopic.source_page_start}-{selectedSubtopic.source_page_end}</p>
                  {selectedSubtopic.confidence !== undefined && (
                    <p>Confidence: {(selectedSubtopic.confidence * 100).toFixed(0)}%</p>
                  )}
                  <p>Version: {selectedSubtopic.version}</p>
                  {selectedSubtopic.quality_score !== undefined && selectedSubtopic.quality_score !== null && (
                    <p className={getQualityScoreColor(selectedSubtopic.quality_score)}>
                      Quality Score: {(selectedSubtopic.quality_score * 100).toFixed(0)}%
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                Select a subtopic to view details
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
