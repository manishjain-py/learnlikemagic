import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { CheckInActivity } from '../api';
import { CheckInActivityResult, PairStruggle } from './CheckInDispatcher';
import { useCheckInAudio } from '../hooks/useCheckInAudio';

/** Fisher-Yates shuffle */
function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function SequenceActivity({ checkIn, onComplete }: Props) {
  const correctOrder = checkIn.sequence_items || [];
  const { play: playTTS } = useCheckInAudio();

  // Shuffled items for display (stable across re-renders)
  const shuffledItems = useMemo(() => shuffle(correctOrder), [correctOrder]);

  const [placedOrder, setPlacedOrder] = useState<string[]>([]); // items placed so far, in order
  const [wrongCount, setWrongCount] = useState(0);
  const [hintShown, setHintShown] = useState(false);
  const [hintCount, setHintCount] = useState(0);
  const [shakeItem, setShakeItem] = useState<string | null>(null);
  const [wrongPicks, setWrongPicks] = useState<Map<number, string[]>>(new Map()); // slot → wrong items
  const [showSuccess, setShowSuccess] = useState(false);

  const nextSlot = placedOrder.length; // 0-based index of next slot to fill

  const handleItemTap = useCallback((item: string) => {
    if (placedOrder.includes(item) || showSuccess) return;

    const expectedItem = correctOrder[nextSlot];

    if (item === expectedItem) {
      const newOrder = [...placedOrder, item];
      setPlacedOrder(newOrder);

      if (newOrder.length >= correctOrder.length) {
        setShowSuccess(true);
        playTTS(checkIn.success_message);
      }
    } else {
      setWrongCount(prev => prev + 1);
      setShakeItem(item);
      setTimeout(() => setShakeItem(null), 500);

      setWrongPicks(prev => {
        const next = new Map(prev);
        const existing = next.get(nextSlot) || [];
        next.set(nextSlot, [...existing, item]);
        return next;
      });

      if (!hintShown) {
        setHintShown(true);
        setHintCount(1);
        playTTS(checkIn.hint);
      } else {
        setHintCount(prev => prev + 1);
      }
    }
  }, [placedOrder, nextSlot, correctOrder, showSuccess, hintShown, checkIn, playTTS]);

  const handleComplete = useCallback(() => {
    const confusedPairs: PairStruggle[] = [];
    wrongPicks.forEach((picks, slotIdx) => {
      if (picks.length > 0 && slotIdx < correctOrder.length) {
        confusedPairs.push({
          left: `Position ${slotIdx + 1}`,
          right: correctOrder[slotIdx],
          wrongCount: picks.length,
          wrongPicks: picks,
        });
      }
    });
    onComplete({
      wrongCount,
      hintsShown: hintCount,
      autoRevealed: 0,
      confusedPairs,
    });
  }, [wrongCount, hintCount, wrongPicks, correctOrder, onComplete]);

  // Auto-complete when success is shown (no Continue button needed)
  useEffect(() => {
    if (showSuccess) handleComplete();
  }, [showSuccess, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      {/* Slots showing placed items */}
      <div className="seq-slots">
        {correctOrder.map((_, i) => (
          <div
            key={i}
            className={
              'seq-slot'
              + (i < placedOrder.length ? ' filled' : '')
              + (i === nextSlot ? ' next' : '')
            }
          >
            <span className="seq-slot-number">{i + 1}</span>
            <span className="seq-slot-value">{placedOrder[i] || ''}</span>
          </div>
        ))}
      </div>

      {/* Available items to tap */}
      {!showSuccess && (
        <div className="seq-items">
          {shuffledItems.map((item, i) => {
            if (placedOrder.includes(item)) return null;
            return (
              <button
                key={i}
                className={
                  'seq-item'
                  + (shakeItem === item ? ' wrong' : '')
                }
                onClick={() => handleItemTap(item)}
                type="button"
              >
                {item}
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
