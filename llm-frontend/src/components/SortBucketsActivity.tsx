import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { CheckInActivity, BucketItem, synthesizeSpeech } from '../api';
import { CheckInActivityResult, PairStruggle } from './CheckInDispatcher';

function playTTS(text: string) {
  synthesizeSpeech(text)
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      audio.play().catch(() => {});
    })
    .catch(() => {});
}

/** Fisher-Yates shuffle */
function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const AUTO_REVEAL_THRESHOLD = 3;

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function SortBucketsActivity({ checkIn, onComplete }: Props) {
  const bucketNames = checkIn.bucket_names || [];
  const items = useMemo(() => shuffle(checkIn.bucket_items || []), [checkIn.bucket_items]);

  const [selectedItem, setSelectedItem] = useState<number | null>(null);
  const [placed, setPlaced] = useState<Map<number, number>>(new Map()); // itemIdx → bucketIdx
  const [wrongAttempts, setWrongAttempts] = useState<Map<number, number>>(new Map());
  const [wrongPicks, setWrongPicks] = useState<Map<number, string[]>>(new Map());
  const [autoRevealed, setAutoRevealed] = useState<Set<number>>(new Set());
  const [hintShown, setHintShown] = useState(false);
  const [hintCount, setHintCount] = useState(0);
  const [totalWrong, setTotalWrong] = useState(0);
  const [showSuccess, setShowSuccess] = useState(false);
  const [shakeBucket, setShakeBucket] = useState<number | null>(null);

  const allPlaced = placed.size + autoRevealed.size >= items.length;

  const handleItemTap = useCallback((idx: number) => {
    if (placed.has(idx) || autoRevealed.has(idx)) return;
    setSelectedItem(idx);
  }, [placed, autoRevealed]);

  const handleBucketTap = useCallback((bucketIdx: number) => {
    if (selectedItem === null) return;

    const item = items[selectedItem];
    if (item.correct_bucket === bucketIdx) {
      // Correct
      setPlaced(prev => new Map(prev).set(selectedItem, bucketIdx));
      setSelectedItem(null);

      const newTotal = placed.size + autoRevealed.size + 1;
      if (newTotal >= items.length) {
        setShowSuccess(true);
        playTTS(checkIn.success_message);
      }
    } else {
      // Wrong
      setTotalWrong(prev => prev + 1);
      const newAttempts = new Map(wrongAttempts);
      const count = (newAttempts.get(selectedItem) || 0) + 1;
      newAttempts.set(selectedItem, count);
      setWrongAttempts(newAttempts);

      setWrongPicks(prev => {
        const next = new Map(prev);
        const existing = next.get(selectedItem) || [];
        next.set(selectedItem, [...existing, bucketNames[bucketIdx]]);
        return next;
      });

      setShakeBucket(bucketIdx);
      setTimeout(() => setShakeBucket(null), 500);

      if (!hintShown || count === 1) {
        setHintShown(true);
        setHintCount(prev => prev + 1);
        if (count === 1) playTTS(checkIn.hint);
      }

      // Auto-reveal after threshold
      if (count >= AUTO_REVEAL_THRESHOLD) {
        setAutoRevealed(prev => new Set(prev).add(selectedItem));
        setPlaced(prev => new Map(prev).set(selectedItem, item.correct_bucket));
        setSelectedItem(null);

        const newTotal = placed.size + autoRevealed.size + 1;
        if (newTotal >= items.length) {
          setShowSuccess(true);
          playTTS(checkIn.success_message);
        }
      }
    }
  }, [selectedItem, items, placed, autoRevealed, wrongAttempts, hintShown, bucketNames, checkIn]);

  const handleComplete = useCallback(() => {
    const confusedPairs: PairStruggle[] = [];
    wrongAttempts.forEach((count, itemIdx) => {
      if (count > 0 && itemIdx < items.length) {
        confusedPairs.push({
          left: items[itemIdx].text,
          right: bucketNames[items[itemIdx].correct_bucket],
          wrongCount: count,
          wrongPicks: wrongPicks.get(itemIdx) || [],
        });
      }
    });
    onComplete({
      wrongCount: totalWrong,
      hintsShown: hintCount,
      autoRevealed: autoRevealed.size,
      confusedPairs,
    });
  }, [wrongAttempts, totalWrong, hintCount, autoRevealed, items, bucketNames, wrongPicks, onComplete]);

  // Auto-complete when success is shown (no Continue button needed)
  useEffect(() => {
    if (showSuccess) handleComplete();
  }, [showSuccess, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      {/* Bucket headers */}
      <div className="sort-buckets">
        {bucketNames.map((name, bIdx) => {
          const bucketItems = items.filter((_, i) => placed.get(i) === bIdx || (autoRevealed.has(i) && items[i].correct_bucket === bIdx));
          return (
            <button
              key={bIdx}
              className={
                'sort-bucket'
                + (selectedItem !== null ? ' active' : '')
                + (shakeBucket === bIdx ? ' wrong' : '')
              }
              onClick={() => handleBucketTap(bIdx)}
              disabled={selectedItem === null || showSuccess}
              type="button"
            >
              <div className="sort-bucket-label">{name}</div>
              <div className="sort-bucket-items">
                {bucketItems.map((item, i) => (
                  <span key={i} className={'sort-placed-item' + (autoRevealed.has(items.indexOf(item)) ? ' auto-revealed' : '')}>
                    {item.text}
                  </span>
                ))}
              </div>
            </button>
          );
        })}
      </div>

      {/* Unsorted items */}
      {!allPlaced && (
        <div className="sort-items">
          {items.map((item, i) => {
            if (placed.has(i) || autoRevealed.has(i)) return null;
            return (
              <button
                key={i}
                className={
                  'sort-item'
                  + (selectedItem === i ? ' selected' : '')
                }
                onClick={() => handleItemTap(i)}
                type="button"
              >
                {item.text}
              </button>
            );
          })}
        </div>
      )}

      {hintShown && !showSuccess && (
        <div className="checkin-hint">{checkIn.hint}</div>
      )}

      {showSuccess && (
        <div className="checkin-success">
          <div className="checkin-success-message">{checkIn.success_message}</div>
        </div>
      )}
    </div>
  );
}
