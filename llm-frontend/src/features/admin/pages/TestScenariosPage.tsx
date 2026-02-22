/**
 * Test Scenarios Page - Admin view for browsing test cases and results
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listTestScenarios,
  getTestScenarioDetail,
  getScenarioScreenshots,
  TestFunctionality,
  TestFunctionalityDetail,
  TestScenarioResult,
  ScreenshotInfo,
} from '../api/adminApi';

// ── Status Badge ──

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const styles: Record<string, { bg: string; text: string; label: string }> = {
    passed: { bg: '#D1FAE5', text: '#065F46', label: 'Passed' },
    failed: { bg: '#FEE2E2', text: '#991B1B', label: 'Failed' },
    not_run: { bg: '#F3F4F6', text: '#6B7280', label: 'Not Run' },
  };
  const s = styles[status] || styles.not_run;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: '600',
        backgroundColor: s.bg,
        color: s.text,
      }}
    >
      {s.label}
    </span>
  );
};

// ── Time Ago ──

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// ── Screenshot Modal ──

const ScreenshotModal: React.FC<{
  screenshots: ScreenshotInfo[];
  onClose: () => void;
}> = ({ screenshots, onClose }) => {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.6)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: 'white',
          borderRadius: '12px',
          padding: '24px',
          maxWidth: '900px',
          maxHeight: '80vh',
          overflow: 'auto',
          width: '90%',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ margin: 0, fontSize: '18px' }}>Screenshots</h3>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '20px',
              cursor: 'pointer',
              color: '#6B7280',
            }}
          >
            X
          </button>
        </div>
        {screenshots.length === 0 ? (
          <p style={{ color: '#6B7280' }}>No screenshots available.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {screenshots.map((ss) => (
              <div key={ss.filename}>
                <img
                  src={ss.url}
                  alt={ss.label}
                  style={{ maxWidth: '100%', borderRadius: '8px', border: '1px solid #E5E7EB' }}
                />
                <p style={{ fontSize: '13px', color: '#6B7280', marginTop: '4px' }}>{ss.label}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Scenario Card ──

const ScenarioCard: React.FC<{
  scenario: TestScenarioResult;
  slug: string;
}> = ({ scenario, slug }) => {
  const [expanded, setExpanded] = useState(false);
  const [screenshots, setScreenshots] = useState<ScreenshotInfo[] | null>(null);
  const [showScreenshots, setShowScreenshots] = useState(false);
  const [loadingScreenshots, setLoadingScreenshots] = useState(false);

  const handleScreenshotsClick = async () => {
    if (!screenshots) {
      setLoadingScreenshots(true);
      try {
        const resp = await getScenarioScreenshots(slug, scenario.id);
        setScreenshots(resp.screenshots);
      } catch {
        setScreenshots([]);
      } finally {
        setLoadingScreenshots(false);
      }
    }
    setShowScreenshots(true);
  };

  return (
    <div
      style={{
        border: '1px solid #E5E7EB',
        borderRadius: '8px',
        marginBottom: '10px',
        backgroundColor: 'white',
      }}
    >
      {/* Header */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '14px 16px',
          cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ color: '#9CA3AF', fontSize: '14px', transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}>
            &#9654;
          </span>
          <span style={{ fontWeight: '500', fontSize: '15px' }}>{scenario.name}</span>
          <span style={{ fontSize: '12px', color: '#9CA3AF' }}>{scenario.id}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {scenario.screenshots.length > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleScreenshotsClick();
              }}
              style={{
                padding: '4px 10px',
                fontSize: '12px',
                borderRadius: '6px',
                border: '1px solid #D1D5DB',
                backgroundColor: 'white',
                cursor: 'pointer',
                color: '#374151',
              }}
            >
              {loadingScreenshots ? '...' : 'Screenshots'}
            </button>
          )}
          <StatusBadge status={scenario.status} />
        </div>
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div style={{ padding: '0 16px 16px 44px', borderTop: '1px solid #F3F4F6' }}>
          <div style={{ marginTop: '12px' }}>
            <p style={{ fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '6px' }}>
              Steps:
            </p>
            <ol type="a" style={{ margin: 0, paddingLeft: '18px', fontSize: '14px', color: '#4B5563', lineHeight: '1.8' }}>
              {scenario.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
          <div style={{ marginTop: '12px' }}>
            <p style={{ fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '4px' }}>
              Expected Result:
            </p>
            <p style={{ fontSize: '14px', color: '#4B5563', margin: 0 }}>
              {scenario.expected_result}
            </p>
          </div>
        </div>
      )}

      {/* Screenshot Modal */}
      {showScreenshots && screenshots && (
        <ScreenshotModal screenshots={screenshots} onClose={() => setShowScreenshots(false)} />
      )}
    </div>
  );
};

// ── Detail View ──

const DetailView: React.FC<{
  detail: TestFunctionalityDetail;
  onBack: () => void;
}> = ({ detail, onBack }) => {
  return (
    <div>
      <button
        onClick={onBack}
        style={{
          background: 'none',
          border: 'none',
          color: '#3B82F6',
          cursor: 'pointer',
          fontSize: '14px',
          marginBottom: '16px',
          padding: 0,
        }}
      >
        &larr; Back to Test Scenarios
      </button>

      <h2 style={{ fontSize: '24px', fontWeight: '600', marginBottom: '8px' }}>{detail.name}</h2>

      {/* Status banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '12px 16px',
          borderRadius: '8px',
          backgroundColor: detail.status === 'passed' ? '#D1FAE5' : detail.status === 'failed' ? '#FEE2E2' : '#F3F4F6',
          marginBottom: '20px',
        }}
      >
        <StatusBadge status={detail.status} />
        {detail.last_tested && (
          <span style={{ fontSize: '13px', color: '#6B7280' }}>
            Tested {timeAgo(detail.last_tested)}
          </span>
        )}
        <span style={{ fontSize: '13px', color: '#9CA3AF' }}>
          {detail.scenarios.length} scenario{detail.scenarios.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Scenarios */}
      {detail.scenarios.map((sc) => (
        <ScenarioCard key={sc.id} scenario={sc} slug={detail.slug} />
      ))}
    </div>
  );
};

// ── Main Page ──

const TestScenariosPage: React.FC = () => {
  const navigate = useNavigate();
  const [functionalities, setFunctionalities] = useState<TestFunctionality[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<TestFunctionalityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    loadList();
  }, []);

  const loadList = async () => {
    try {
      setLoading(true);
      setError(null);
      const resp = await listTestScenarios();
      setFunctionalities(resp.functionalities);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load test scenarios');
    } finally {
      setLoading(false);
    }
  };

  const selectFunctionality = async (slug: string) => {
    setSelectedSlug(slug);
    setDetailLoading(true);
    try {
      const resp = await getTestScenarioDetail(slug);
      setDetail(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load detail');
    } finally {
      setDetailLoading(false);
    }
  };

  const goBack = () => {
    setSelectedSlug(null);
    setDetail(null);
  };

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: '600', marginBottom: '10px' }}>
          Test Scenarios
        </h1>
        <p style={{ color: '#6B7280' }}>
          Browse test cases and view latest E2E test results
        </p>
      </div>

      {/* Nav buttons */}
      <div style={{ marginBottom: '20px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
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
          Guidelines
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
        <button
          onClick={() => navigate('/admin/docs')}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Docs
        </button>
        <button
          onClick={() => navigate('/admin/llm-config')}
          style={{
            padding: '10px 20px',
            backgroundColor: 'white',
            color: '#374151',
            border: '1px solid #D1D5DB',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          LLM Config
        </button>
        <button
          onClick={loadList}
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

      {/* Error */}
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

      {/* Detail View */}
      {selectedSlug && (
        <>
          {detailLoading ? (
            <div style={{ textAlign: 'center', padding: '40px' }}>
              <p>Loading scenarios...</p>
            </div>
          ) : detail ? (
            <DetailView detail={detail} onBack={goBack} />
          ) : null}
        </>
      )}

      {/* List View */}
      {!selectedSlug && (
        <>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '40px' }}>
              <p>Loading test scenarios...</p>
            </div>
          ) : functionalities.length === 0 ? (
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
                No test cases found
              </p>
              <p style={{ color: '#9CA3AF' }}>
                Run the e2e-updater to generate test case documents under docs/test-cases/
              </p>
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                gap: '20px',
              }}
            >
              {functionalities.map((func) => (
                <div
                  key={func.slug}
                  onClick={() => selectFunctionality(func.slug)}
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
                  <div style={{ marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <StatusBadge status={func.status} />
                    <span
                      style={{
                        fontSize: '12px',
                        color: '#6B7280',
                        backgroundColor: '#F3F4F6',
                        padding: '2px 8px',
                        borderRadius: '10px',
                      }}
                    >
                      {func.scenario_count} scenario{func.scenario_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <h3
                    style={{
                      fontSize: '18px',
                      fontWeight: '600',
                      marginBottom: '8px',
                    }}
                  >
                    {func.name}
                  </h3>
                  {func.status !== 'not_run' && (
                    <div style={{ fontSize: '13px', color: '#6B7280' }}>
                      <span style={{ color: '#10B981' }}>{func.passed} passed</span>
                      {func.failed > 0 && (
                        <span style={{ color: '#EF4444', marginLeft: '8px' }}>
                          {func.failed} failed
                        </span>
                      )}
                    </div>
                  )}
                  {func.last_tested && (
                    <p style={{ fontSize: '12px', color: '#9CA3AF', marginTop: '8px', marginBottom: 0 }}>
                      Tested {timeAgo(func.last_tested)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default TestScenariosPage;
