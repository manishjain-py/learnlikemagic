import React from 'react';

interface Props {
  name: string;
  /** Display labels (in display order) of items currently assigned to this bucket. */
  itemsInBucket: string[];
  /** Called when the student taps the bucket to drop the active item. */
  onDrop?: () => void;
  active?: boolean;
  disabled?: boolean;
}

/**
 * A visual drop-target. Used by SortBucketsCapture and SwipeClassifyCapture.
 * The parent drives interaction — this component is pure presentational.
 */
export default function BucketZone({
  name, itemsInBucket, onDrop, active, disabled,
}: Props) {
  return (
    <div
      onClick={() => { if (onDrop && !disabled) onDrop(); }}
      style={{
        flex: 1,
        border: active ? '2px solid #0891B2' : '2px dashed #D1D5DB',
        borderRadius: '10px',
        padding: '12px',
        backgroundColor: active ? '#ECFEFF' : '#FAFAFA',
        cursor: onDrop && !disabled ? 'pointer' : 'default',
        minHeight: '120px',
        opacity: disabled ? 0.6 : 1,
      }}
    >
      <div style={{
        fontSize: '13px', fontWeight: 700, color: '#111827',
        marginBottom: '8px', textAlign: 'center',
      }}>
        {name}
      </div>
      {itemsInBucket.map(item => (
        <div key={item} style={{
          padding: '6px 10px', marginBottom: '4px',
          backgroundColor: 'white', borderRadius: '6px',
          fontSize: '13px', color: '#374151',
          border: '1px solid #E5E7EB',
        }}>
          {item}
        </div>
      ))}
      {itemsInBucket.length === 0 && (
        <div style={{
          textAlign: 'center', color: '#9CA3AF', fontSize: '12px',
          fontStyle: 'italic', paddingTop: '16px',
        }}>
          (empty)
        </div>
      )}
    </div>
  );
}
