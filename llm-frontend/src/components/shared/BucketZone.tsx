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
  const cls = ['practice-bucket', active && 'active'].filter(Boolean).join(' ');
  return (
    <div
      className={cls}
      onClick={() => { if (onDrop && !disabled) onDrop(); }}
      style={{ cursor: onDrop && !disabled ? 'pointer' : 'default', opacity: disabled ? 0.6 : 1 }}
    >
      <div className="practice-bucket-label">{name}</div>
      {itemsInBucket.map(item => (
        <div key={item} className="practice-bucket-item">{item}</div>
      ))}
      {itemsInBucket.length === 0 && (
        <div className="practice-bucket-empty">(empty)</div>
      )}
    </div>
  );
}
