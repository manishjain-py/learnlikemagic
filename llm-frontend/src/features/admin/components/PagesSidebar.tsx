/**
 * Pages Sidebar - Shows list of approved pages
 *
 * Highlights pages that have not yet been processed for guidelines
 * when guidelines exist (processedPages is non-empty).
 */

import React from 'react';
import { PageInfo } from '../types';
import { retryPageOcr } from '../api/adminApi';

interface PagesSidebarProps {
  pages: PageInfo[];
  selectedPage: number | null;
  onSelectPage: (pageNum: number) => void;
  processedPages?: Set<number>;
  bookId?: string;
  onPageProcessed?: () => void;
}

// OCR status indicator
const OcrStatusIcon: React.FC<{ status?: string; pageNum: number; bookId?: string; onRetry?: () => void }> = ({ status, pageNum, bookId, onRetry }) => {
  // Treat missing ocr_status as completed (legacy pages)
  const effectiveStatus = status || 'completed';

  switch (effectiveStatus) {
    case 'completed':
      return <span style={{ color: '#10B981', fontSize: '12px' }} title="OCR complete">&#9679;</span>;
    case 'processing':
      return <span style={{ color: '#F59E0B', fontSize: '12px', animation: 'pulse 1s infinite' }} title="OCR processing">&#9679;</span>;
    case 'failed':
      return (
        <span
          style={{ color: '#EF4444', fontSize: '12px', cursor: bookId ? 'pointer' : 'default' }}
          title="OCR failed - click to retry"
          onClick={async (e) => {
            e.stopPropagation();
            if (bookId) {
              try {
                await retryPageOcr(bookId, pageNum);
                onRetry?.();
              } catch {
                // Silently handle
              }
            }
          }}
        >
          &#10007;
        </span>
      );
    case 'pending':
      return <span style={{ color: '#D1D5DB', fontSize: '12px' }} title="OCR pending">&#9675;</span>;
    default:
      return null;
  }
};

const PagesSidebar: React.FC<PagesSidebarProps> = ({ pages, selectedPage, onSelectPage, processedPages, bookId, onPageProcessed }) => {
  const approvedPages = pages.filter((p) => p.status === 'approved');
  const pendingPages = pages.filter((p) => p.status === 'pending_review');
  const displayPages = pages;
  const hasGuidelines = processedPages != null && processedPages.size > 0;
  const unprocessedCount = hasGuidelines
    ? approvedPages.filter((p) => !processedPages.has(p.page_num)).length
    : 0;

  return (
    <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '4px' }}>
        Pages ({pages.length})
      </h3>
      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '12px' }}>
        {approvedPages.length} approved{pendingPages.length > 0 && `, ${pendingPages.length} pending review`}
        {hasGuidelines && unprocessedCount > 0 && (
          <span style={{ color: '#C2410C' }}> &middot; {unprocessedCount} not in guidelines</span>
        )}
      </div>

      {pages.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '20px', color: '#9CA3AF', fontSize: '14px' }}>
          No pages yet
        </div>
      ) : (
        <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
          {displayPages.map((page) => {
            const isProcessed = hasGuidelines && processedPages.has(page.page_num);
            const isUnprocessed = hasGuidelines && !processedPages.has(page.page_num);
            const isSelected = selectedPage === page.page_num;

            // Determine background color
            let bgColor = 'white';
            if (isSelected) {
              bgColor = '#EBF5FF';
            } else if (isUnprocessed) {
              bgColor = '#FFF7ED'; // Light orange tint for unprocessed
            }

            return (
              <div
                key={page.page_num}
                onClick={() => onSelectPage(page.page_num)}
                style={{
                  padding: '12px',
                  marginBottom: '8px',
                  borderRadius: '6px',
                  border: isUnprocessed
                    ? '1px solid #FED7AA'
                    : '1px solid #E5E7EB',
                  cursor: 'pointer',
                  backgroundColor: bgColor,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = isUnprocessed ? '#FFEDD5' : '#F9FAFB';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = isUnprocessed ? '#FFF7ED' : 'white';
                  }
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div
                    style={{
                      width: '40px',
                      height: '50px',
                      backgroundColor: isUnprocessed ? '#FFEDD5' : '#F3F4F6',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '12px',
                      fontWeight: '500',
                      color: isUnprocessed ? '#C2410C' : '#6B7280',
                    }}
                  >
                    {page.page_num}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', fontWeight: '500', marginBottom: '2px' }}>
                      Page {page.page_num}
                      <OcrStatusIcon
                        status={page.ocr_status}
                        pageNum={page.page_num}
                        bookId={bookId}
                        onRetry={onPageProcessed}
                      />
                    </div>
                    {page.status === 'pending_review' ? (
                      <div style={{ fontSize: '12px', color: '#F59E0B', fontWeight: '500' }}>
                        Pending review
                      </div>
                    ) : isUnprocessed ? (
                      <div style={{ fontSize: '12px', color: '#C2410C', fontWeight: '500' }}>
                        ● New — not in guidelines
                      </div>
                    ) : (
                      <div style={{ fontSize: '12px', color: '#10B981' }}>
                        ✓ {isProcessed ? 'In guidelines' : 'Approved'}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PagesSidebar;
