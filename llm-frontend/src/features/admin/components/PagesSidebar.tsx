/**
 * Pages Sidebar - Shows list of approved pages
 */

import React from 'react';
import { PageInfo } from '../types';

interface PagesSidebarProps {
  pages: PageInfo[];
  selectedPage: number | null;
  onSelectPage: (pageNum: number) => void;
}

const PagesSidebar: React.FC<PagesSidebarProps> = ({ pages, selectedPage, onSelectPage }) => {
  const approvedPages = pages.filter((p) => p.status === 'approved');

  return (
    <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
      <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px' }}>
        Approved Pages ({approvedPages.length})
      </h3>

      {approvedPages.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '20px', color: '#9CA3AF', fontSize: '14px' }}>
          No approved pages yet
        </div>
      ) : (
        <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
          {approvedPages.map((page) => (
            <div
              key={page.page_num}
              onClick={() => onSelectPage(page.page_num)}
              style={{
                padding: '12px',
                marginBottom: '8px',
                borderRadius: '6px',
                border: '1px solid #E5E7EB',
                cursor: 'pointer',
                backgroundColor: selectedPage === page.page_num ? '#EBF5FF' : 'white',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                if (selectedPage !== page.page_num) {
                  e.currentTarget.style.backgroundColor = '#F9FAFB';
                }
              }}
              onMouseLeave={(e) => {
                if (selectedPage !== page.page_num) {
                  e.currentTarget.style.backgroundColor = 'white';
                }
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div
                  style={{
                    width: '40px',
                    height: '50px',
                    backgroundColor: '#F3F4F6',
                    borderRadius: '4px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '12px',
                    fontWeight: '500',
                    color: '#6B7280',
                  }}
                >
                  {page.page_num}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '2px' }}>
                    Page {page.page_num}
                  </div>
                  <div style={{ fontSize: '12px', color: '#10B981' }}>
                    ✓ Approved
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default PagesSidebar;
