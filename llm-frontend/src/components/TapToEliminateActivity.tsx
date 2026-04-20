import React, { useState, useCallback, useEffect } from 'react';
import { CheckInActivity } from '../api';
import { CheckInActivityResult } from './CheckInDispatcher';
import { useCheckInAudio } from '../hooks/useCheckInAudio';

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function TapToEliminateActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;
  const { play: playTTS } = useCheckInAudio();

  const [eliminated, setEliminated] = useState<Set<number>>(new Set());
  const [wrongCount, setWrongCount] = useState(0);
  const [hintShown, setHintShown] = useState(false);
  const [shakeIdx, setShakeIdx] = useState<number | null>(null);
  const [showSuccess, setShowSuccess] = useState(false);
  const [wrongPicks, setWrongPicks] = useState<string[]>([]);

  const remaining = options.length - eliminated.size;

  const handleTap = useCallback((idx: number) => {
    if (showSuccess || eliminated.has(idx)) return;

    if (idx === correctIdx) {
      // Tapped the correct answer — that's wrong (should eliminate wrong ones)
      setWrongCount(prev => prev + 1);
      setWrongPicks(prev => [...prev, options[idx]]);
      setShakeIdx(idx);
      setTimeout(() => setShakeIdx(null), 500);
      if (!hintShown) {
        setHintShown(true);
        playTTS(checkIn.hint);
      }
    } else {
      // Correct elimination — cross out a wrong answer
      const next = new Set(eliminated);
      next.add(idx);
      setEliminated(next);

      // Check if only the correct answer remains
      if (options.length - next.size === 1) {
        setShowSuccess(true);
        playTTS(checkIn.success_message);
      }
    }
  }, [showSuccess, eliminated, correctIdx, options, hintShown, checkIn, playTTS]);

  const handleComplete = useCallback(() => {
    onComplete({
      wrongCount,
      hintsShown: hintShown ? 1 : 0,
      autoRevealed: 0,
      confusedPairs: wrongCount > 0
        ? [{ left: checkIn.instruction, right: options[correctIdx], wrongCount, wrongPicks }]
        : [],
    });
  }, [wrongCount, hintShown, checkIn.instruction, options, correctIdx, wrongPicks, onComplete]);

  // Auto-complete when success shows
  useEffect(() => {
    if (showSuccess) handleComplete();
  }, [showSuccess, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="eliminate-status">
        {remaining > 1
          ? `Tap a wrong answer to cross it out (${remaining - 1} left to remove)`
          : null}
      </div>

      <div className="eliminate-options">
        {options.map((opt, i) => (
          <button
            key={i}
            className={
              'eliminate-option'
              + (eliminated.has(i) ? ' eliminated' : '')
              + (showSuccess && i === correctIdx ? ' correct' : '')
              + (shakeIdx === i ? ' wrong' : '')
            }
            onClick={() => handleTap(i)}
            disabled={showSuccess || eliminated.has(i)}
            type="button"
          >
            <span className={eliminated.has(i) ? 'strikethrough' : ''}>{opt}</span>
          </button>
        ))}
      </div>

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
