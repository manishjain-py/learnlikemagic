/**
 * Book Status Badge Component
 */

import React from 'react';
import { BookStatus, STATUS_LABELS, STATUS_COLORS } from '../types';

interface BookStatusBadgeProps {
  status: BookStatus;
}

const BookStatusBadge: React.FC<BookStatusBadgeProps> = ({ status }) => {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: '500',
        backgroundColor: `${STATUS_COLORS[status]}20`,
        color: STATUS_COLORS[status],
        border: `1px solid ${STATUS_COLORS[status]}40`,
      }}
    >
      {STATUS_LABELS[status]}
    </span>
  );
};

export default BookStatusBadge;
