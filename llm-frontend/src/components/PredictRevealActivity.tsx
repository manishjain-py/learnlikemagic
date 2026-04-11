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

export default function PredictRevealActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;

  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [wasCorrect, setWasCorrect] = useState(false);

  const handlePick = useCallback((idx: number) => {
    if (selectedIdx !== null) return;
    setSelectedIdx(idx);
    const correct = idx === correctIdx;
    setWasCorrect(correct);
    // Short pause then reveal
    setTimeout(() => {
      setRevealed(true);
      playTTS(correct ? checkIn.success_message : checkIn.reveal_text || checkIn.success_message);
    }, 600);
  }, [selectedIdx, correctIdx, checkIn]);

  const handleComplete = useCallback(() => {
    onComplete({
      wrongCount: wasCorrect ? 0 : 1,
      hintsShown: 0,
      autoRevealed: 0,
      confusedPairs: wasCorrect ? [] : [{
        left: checkIn.instruction,
        right: options[correctIdx],
        wrongCount: 1,
        wrongPicks: selectedIdx !== null ? [options[selectedIdx]] : [],
      }],
    });
  }, [wasCorrect, checkIn.instruction, options, correctIdx, selectedIdx, onComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="predict-options">
        {options.map((opt, i) => (
          <button
            key={i}
            className={
              'predict-option'
              + (selectedIdx === i ? ' selected' : '')
              + (revealed && i === correctIdx ? ' correct' : '')
              + (revealed && selectedIdx === i && i !== correctIdx ? ' wrong-pick' : '')
            }
            onClick={() => handlePick(i)}
            disabled={selectedIdx !== null}
            type="button"
          >
            {opt}
          </button>
        ))}
      </div>

      {revealed && (
        <div className={wasCorrect ? 'checkin-success' : 'predict-reveal'}>
          <div className={wasCorrect ? 'checkin-success-message' : 'predict-reveal-text'}>
            {wasCorrect ? checkIn.success_message : checkIn.reveal_text}
          </div>
          <button className="checkin-continue-btn" onClick={handleComplete} type="button">
            Got it!
          </button>
        </div>
      )}
    </div>
  );
}
