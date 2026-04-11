import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
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

export default function SwipeClassifyActivity({ checkIn, onComplete }: Props) {
  const categories = checkIn.bucket_names || [];
  const items = useMemo(() => shuffle(checkIn.bucket_items || []), [checkIn.bucket_items]);

  const [currentIdx, setCurrentIdx] = useState(0);
  const [wrongAttempts, setWrongAttempts] = useState<Map<number, number>>(new Map());
  const [wrongPicks, setWrongPicks] = useState<Map<number, string[]>>(new Map());
  const [totalWrong, setTotalWrong] = useState(0);
  const [hintCount, setHintCount] = useState(0);
  const [showSuccess, setShowSuccess] = useState(false);
  const [swipeDir, setSwipeDir] = useState<'left' | 'right' | null>(null);
  const [shakeCard, setShakeCard] = useState(false);

  // Touch tracking
  const touchStartX = useRef(0);
  const cardRef = useRef<HTMLDivElement>(null);

  const currentItem = items[currentIdx];
  const isFinished = currentIdx >= items.length;

  const handleClassify = useCallback((bucketIdx: number) => {
    if (isFinished || !currentItem) return;

    if (currentItem.correct_bucket === bucketIdx) {
      // Correct — animate swipe direction then advance
      setSwipeDir(bucketIdx === 0 ? 'left' : 'right');
      setTimeout(() => {
        setSwipeDir(null);
        const nextIdx = currentIdx + 1;
        setCurrentIdx(nextIdx);
        if (nextIdx >= items.length) {
          setShowSuccess(true);
          playTTS(checkIn.success_message);
        }
      }, 300);
    } else {
      // Wrong
      setTotalWrong(prev => prev + 1);
      setWrongAttempts(prev => {
        const next = new Map(prev);
        next.set(currentIdx, (next.get(currentIdx) || 0) + 1);
        return next;
      });
      setWrongPicks(prev => {
        const next = new Map(prev);
        const existing = next.get(currentIdx) || [];
        next.set(currentIdx, [...existing, categories[bucketIdx]]);
        return next;
      });
      setShakeCard(true);
      setTimeout(() => setShakeCard(false), 500);

      const attempts = (wrongAttempts.get(currentIdx) || 0) + 1;
      if (attempts === 1) {
        setHintCount(prev => prev + 1);
        playTTS(checkIn.hint);
      }
    }
  }, [isFinished, currentItem, currentIdx, items, categories, wrongAttempts, checkIn]);

  // Touch handlers for swipe gesture
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 50) {
      handleClassify(dx < 0 ? 0 : 1);
    }
  }, [handleClassify]);

  const handleComplete = useCallback(() => {
    const confusedPairs: PairStruggle[] = [];
    wrongAttempts.forEach((count, itemIdx) => {
      if (count > 0 && itemIdx < items.length) {
        confusedPairs.push({
          left: items[itemIdx].text,
          right: categories[items[itemIdx].correct_bucket],
          wrongCount: count,
          wrongPicks: wrongPicks.get(itemIdx) || [],
        });
      }
    });
    onComplete({
      wrongCount: totalWrong,
      hintsShown: hintCount,
      autoRevealed: 0,
      confusedPairs,
    });
  }, [wrongAttempts, totalWrong, hintCount, items, categories, wrongPicks, onComplete]);

  useEffect(() => {
    if (showSuccess) handleComplete();
  }, [showSuccess, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      {/* Category labels */}
      <div className="swipe-labels">
        <span className="swipe-label-left">{categories[0]}</span>
        <span className="swipe-label-right">{categories[1]}</span>
      </div>

      {/* Current card */}
      {!isFinished && currentItem && (
        <div
          ref={cardRef}
          className={
            'swipe-card'
            + (swipeDir === 'left' ? ' swipe-left' : '')
            + (swipeDir === 'right' ? ' swipe-right' : '')
            + (shakeCard ? ' wrong' : '')
          }
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className="swipe-card-text">{currentItem.text}</div>
          <div className="swipe-card-counter">{currentIdx + 1} / {items.length}</div>
        </div>
      )}

      {/* Tap buttons (fallback for non-swipe) */}
      {!isFinished && currentItem && (
        <div className="swipe-buttons">
          <button
            className="swipe-btn swipe-btn-left"
            onClick={() => handleClassify(0)}
            disabled={swipeDir !== null}
            type="button"
          >
            {categories[0]}
          </button>
          <button
            className="swipe-btn swipe-btn-right"
            onClick={() => handleClassify(1)}
            disabled={swipeDir !== null}
            type="button"
          >
            {categories[1]}
          </button>
        </div>
      )}

      {!showSuccess && hintCount > 0 && !swipeDir && (
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
