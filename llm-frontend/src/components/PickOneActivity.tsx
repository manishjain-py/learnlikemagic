import React, { useState, useCallback } from 'react';
import { CheckInActivity } from '../api';
import { CheckInActivityResult } from './CheckInDispatcher';
import { useCheckInAudio } from '../hooks/useCheckInAudio';

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function PickOneActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;
  const { play: playTTS } = useCheckInAudio();

  const [selected, setSelected] = useState<number | null>(null);
  const [isCorrect, setIsCorrect] = useState<boolean | null>(null);
  const [wrongCount, setWrongCount] = useState(0);
  const [hintShown, setHintShown] = useState(false);
  const [shakeIdx, setShakeIdx] = useState<number | null>(null);
  const [wrongPicks, setWrongPicks] = useState<string[]>([]);

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

  const handleTap = useCallback((idx: number) => {
    if (isCorrect !== null) return; // already answered

    if (idx === correctIdx) {
      setSelected(idx);
      setIsCorrect(true);
      playTTS(checkIn.success_message);
      handleComplete();
    } else {
      setWrongCount(prev => prev + 1);
      setWrongPicks(prev => [...prev, options[idx]]);
      setShakeIdx(idx);
      setTimeout(() => setShakeIdx(null), 500);
      if (!hintShown) {
        setHintShown(true);
        playTTS(checkIn.hint);
      }
    }
  }, [isCorrect, correctIdx, hintShown, options, checkIn, handleComplete, playTTS]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="checkin-options">
        {options.map((opt, i) => (
          <button
            key={i}
            className={
              'checkin-option-btn'
              + (selected === i && isCorrect ? ' correct' : '')
              + (shakeIdx === i ? ' wrong' : '')
            }
            onClick={() => handleTap(i)}
            disabled={isCorrect !== null}
            type="button"
          >
            {opt}
          </button>
        ))}
      </div>

      {hintShown && !isCorrect && (
        <div className="checkin-hint">{checkIn.hint}</div>
      )}

      {isCorrect && (
        <div className="checkin-success">
          <div className="checkin-success-message">{checkIn.success_message}</div>
        </div>
      )}
    </div>
  );
}
