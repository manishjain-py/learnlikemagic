import React, { useState, useCallback } from 'react';
import { CheckInActivity, synthesizeSpeech } from '../api';
import { CheckInActivityResult } from './CheckInDispatcher';

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

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function SpotTheErrorActivity({ checkIn, onComplete }: Props) {
  const steps = checkIn.error_steps || [];
  const errorIdx = checkIn.error_index ?? 0;

  const [tappedIdx, setTappedIdx] = useState<number | null>(null);
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
        ? [{ left: checkIn.instruction, right: steps[errorIdx], wrongCount, wrongPicks }]
        : [],
    });
  }, [wrongCount, hintShown, checkIn.instruction, steps, errorIdx, wrongPicks, onComplete]);

  const handleTap = useCallback((idx: number) => {
    if (isCorrect !== null) return;

    if (idx === errorIdx) {
      setTappedIdx(idx);
      setIsCorrect(true);
      playTTS(checkIn.success_message);
      handleComplete();
    } else {
      setWrongCount(prev => prev + 1);
      setWrongPicks(prev => [...prev, steps[idx]]);
      setShakeIdx(idx);
      setTimeout(() => setShakeIdx(null), 500);
      if (!hintShown) {
        setHintShown(true);
        playTTS(checkIn.hint);
      }
    }
  }, [isCorrect, errorIdx, hintShown, steps, checkIn, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="error-steps">
        {steps.map((step, i) => (
          <button
            key={i}
            className={
              'error-step'
              + (tappedIdx === i && isCorrect ? ' correct' : '')
              + (shakeIdx === i ? ' wrong' : '')
            }
            onClick={() => handleTap(i)}
            disabled={isCorrect !== null}
            type="button"
          >
            <span className="error-step-num">{i + 1}</span>
            <span className="error-step-text">{step}</span>
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
