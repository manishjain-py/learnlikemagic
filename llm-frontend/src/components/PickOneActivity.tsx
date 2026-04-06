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

export default function PickOneActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;

  const [selected, setSelected] = useState<number | null>(null);
  const [isCorrect, setIsCorrect] = useState<boolean | null>(null);
  const [wrongCount, setWrongCount] = useState(0);
  const [hintShown, setHintShown] = useState(false);
  const [shakeIdx, setShakeIdx] = useState<number | null>(null);
  const [wrongPicks, setWrongPicks] = useState<string[]>([]);

  const handleTap = useCallback((idx: number) => {
    if (isCorrect !== null) return; // already answered

    if (idx === correctIdx) {
      setSelected(idx);
      setIsCorrect(true);
      playTTS(checkIn.success_message);
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
  }, [isCorrect, correctIdx, hintShown, options, checkIn]);

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
          <button className="checkin-continue-btn" onClick={handleComplete} type="button">
            Continue
          </button>
        </div>
      )}
    </div>
  );
}
