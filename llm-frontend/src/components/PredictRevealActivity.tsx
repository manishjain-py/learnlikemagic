import React, { useState, useCallback, useEffect } from 'react';
import { CheckInActivity } from '../api';
import { CheckInActivityResult } from './CheckInDispatcher';
import { useCheckInAudio } from '../hooks/useCheckInAudio';

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function PredictRevealActivity({ checkIn, onComplete }: Props) {
  const options = checkIn.options || [];
  const correctIdx = checkIn.correct_index ?? 0;
  const { play: playTTS } = useCheckInAudio();

  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [wasCorrect, setWasCorrect] = useState(false);

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

  const handlePick = useCallback((idx: number) => {
    if (selectedIdx !== null) return;
    setSelectedIdx(idx);
    const correct = idx === correctIdx;
    setWasCorrect(correct);
    // Short pause then reveal
    setTimeout(() => {
      setRevealed(true);
      if (correct) {
        playTTS(checkIn.success_message, checkIn.success_audio_url);
      } else {
        const text = checkIn.reveal_text || checkIn.success_message;
        const url = checkIn.reveal_text ? checkIn.reveal_audio_url : checkIn.success_audio_url;
        playTTS(text, url);
      }
    }, 600);
  }, [selectedIdx, correctIdx, checkIn, playTTS]);

  // Auto-complete when revealed (no extra buttons)
  useEffect(() => {
    if (revealed) handleComplete();
  }, [revealed, handleComplete]);

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
        </div>
      )}
    </div>
  );
}
