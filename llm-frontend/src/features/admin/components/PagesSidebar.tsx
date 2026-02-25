/**
 * Pages Sidebar - Shows list of approved pages
 *
 * Highlights pages that have not yet been processed for guidelines
 * when guidelines exist (processedPages is non-empty).
 */

import React from 'react';
import { PageInfo } from '../types';

interface PagesSidebarProps {
  pages: PageInfo[];
  selectedPage: number | null;
  onSelectPage: (pageNum: number) => void;
  processedPages?: Set<number>;
}

const PagesSidebar: React.FC<PagesSidebarProps> = ({ pages, selectedPage, onSelectPage, processedPages }) => {
  const approvedPages = pages.filter((p) => p.status === 'approved');
  const hasGuidelines = processedPages != null && processedPages.size > 0;
  const unprocessedCount = hasGuidelines
    ? approvedPages.filter((p) => !processedPages.has(p.page_num)).length
    : 0;

  return (
    <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '4px' }}>
        Approved Pages ({approvedPages.length})
      </h3>
      {hasGuidelines && unprocessedCount > 0 && (
        <div style={{ fontSize: '13px', color: '#C2410C', marginBottom: '12px' }}>
          {unprocessedCount} {unprocessedCount === 1 ? 'page' : 'pages'} not in guidelines
        </div>
      )}
      {!(hasGuidelines && unprocessedCount > 0) && (
        <div style={{ marginBottom: '16px' }} />
      )}

      {approvedPages.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '20px', color: '#9CA3AF', fontSize: '14px' }}>
          No approved pages yet
        </div>
      ) : (
        <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
          {approvedPages.map((page) => {
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
                    <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '2px' }}>
                      Page {page.page_num}
                    </div>
                    {isUnprocessed ? (
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
