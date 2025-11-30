/**
 * Book Status Badge Component
 */

import React from 'react';
import { DisplayStatus, getStatusLabel, getStatusColor } from '../utils/bookStatus';

interface BookStatusBadgeProps {
  status: DisplayStatus;
}

const BookStatusBadge: React.FC<BookStatusBadgeProps> = ({ status }) => {
  const colorType = getStatusColor(status);

  // Map color types to hex colors
  const colors = {
    default: '#6B7280',
    primary: '#8B5CF6',
    secondary: '#EC4899',
    error: '#EF4444',
    info: '#3B82F6',
    success: '#059669',
    warning: '#F59E0B',
  };

  const color = colors[colorType];

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: '500',
        backgroundColor: `${color}20`,
        color: color,
        border: `1px solid ${color}40`,
      }}
    >
      {getStatusLabel(status)}
    </span>
  );
};

export default BookStatusBadge;
