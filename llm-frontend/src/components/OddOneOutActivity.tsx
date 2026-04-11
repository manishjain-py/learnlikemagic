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

export default function OddOneOutActivity({ checkIn, onComplete }: Props) {
  const items = checkIn.odd_items || [];
  const oddIdx = checkIn.odd_index ?? 0;

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
        ? [{ left: checkIn.instruction, right: items[oddIdx], wrongCount, wrongPicks }]
        : [],
    });
  }, [wrongCount, hintShown, checkIn.instruction, items, oddIdx, wrongPicks, onComplete]);

  const handleTap = useCallback((idx: number) => {
    if (isCorrect !== null) return;

    if (idx === oddIdx) {
      setTappedIdx(idx);
      setIsCorrect(true);
      playTTS(checkIn.success_message);
      handleComplete();
    } else {
      setWrongCount(prev => prev + 1);
      setWrongPicks(prev => [...prev, items[idx]]);
      setShakeIdx(idx);
      setTimeout(() => setShakeIdx(null), 500);
      if (!hintShown) {
        setHintShown(true);
        playTTS(checkIn.hint);
      }
    }
  }, [isCorrect, oddIdx, hintShown, items, checkIn, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="odd-items">
        {items.map((item, i) => (
          <button
            key={i}
            className={
              'odd-item'
              + (tappedIdx === i && isCorrect ? ' correct' : '')
              + (shakeIdx === i ? ' wrong' : '')
            }
            onClick={() => handleTap(i)}
            disabled={isCorrect !== null}
            type="button"
          >
            {item}
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
