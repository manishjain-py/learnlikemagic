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

export default function TrueFalseActivity({ checkIn, onComplete }: Props) {
  const correctAnswer = checkIn.correct_answer ?? true;

  const [answered, setAnswered] = useState<boolean | null>(null);
  const [isCorrect, setIsCorrect] = useState<boolean | null>(null);
  const [wrongCount, setWrongCount] = useState(0);
  const [hintShown, setHintShown] = useState(false);
  const [wrongPicks, setWrongPicks] = useState<string[]>([]);

  const handleTap = useCallback((choice: boolean) => {
    if (isCorrect !== null) return;

    if (choice === correctAnswer) {
      setAnswered(choice);
      setIsCorrect(true);
      playTTS(checkIn.success_message);
    } else {
      setWrongCount(prev => prev + 1);
      setWrongPicks(prev => [...prev, choice ? 'Right' : 'Wrong']);
      if (!hintShown) {
        setHintShown(true);
        playTTS(checkIn.hint);
      }
    }
  }, [isCorrect, correctAnswer, hintShown, checkIn]);

  const handleComplete = useCallback(() => {
    onComplete({
      wrongCount,
      hintsShown: hintShown ? 1 : 0,
      autoRevealed: 0,
      confusedPairs: wrongCount > 0
        ? [{ left: checkIn.statement || '', right: correctAnswer ? 'Right' : 'Wrong', wrongCount, wrongPicks }]
        : [],
    });
  }, [wrongCount, hintShown, checkIn.statement, correctAnswer, wrongPicks, onComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>
      <div className="tf-statement">{checkIn.statement}</div>

      <div className="tf-buttons">
        <button
          className={
            'tf-btn tf-right'
            + (answered === true && isCorrect ? ' correct' : '')
            + (answered !== true && wrongCount > 0 && !isCorrect ? '' : '')
          }
          onClick={() => handleTap(true)}
          disabled={isCorrect !== null}
          type="button"
        >
          Right
        </button>
        <button
          className={
            'tf-btn tf-wrong'
            + (answered === false && isCorrect ? ' correct' : '')
          }
          onClick={() => handleTap(false)}
          disabled={isCorrect !== null}
          type="button"
        >
          Wrong
        </button>
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
