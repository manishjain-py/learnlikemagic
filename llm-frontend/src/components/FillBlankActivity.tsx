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

export default function FillBlankActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;
  const instruction = checkIn.instruction || '';

  // Split on ___ to render the blank visually
  const parts = instruction.split('___');
  const hasBlanks = parts.length > 1;

  const [filledValue, setFilledValue] = useState<string | null>(null);
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
        ? [{ left: instruction, right: options[correctIdx], wrongCount, wrongPicks }]
        : [],
    });
  }, [wrongCount, hintShown, instruction, options, correctIdx, wrongPicks, onComplete]);

  const handleTap = useCallback((idx: number) => {
    if (isCorrect !== null) return;

    if (idx === correctIdx) {
      setFilledValue(options[idx]);
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
  }, [isCorrect, correctIdx, hintShown, options, checkIn, handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="fill-sentence">
        {hasBlanks ? (
          <>
            <span>{parts[0]}</span>
            <span className={'fill-blank-slot' + (filledValue ? ' filled' : '')}>
              {filledValue || '___'}
            </span>
            <span>{parts[1]}</span>
          </>
        ) : (
          <span>{instruction}</span>
        )}
      </div>

      <div className="checkin-options">
        {options.map((opt, i) => (
          <button
            key={i}
            className={
              'checkin-option-btn'
              + (filledValue === opt && isCorrect ? ' correct' : '')
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
