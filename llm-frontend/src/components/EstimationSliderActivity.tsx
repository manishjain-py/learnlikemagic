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

export default function EstimationSliderActivity({ checkIn, onComplete }: Props) {
  const min = checkIn.slider_min ?? 0;
  const max = checkIn.slider_max ?? 100;
  const correct = checkIn.correct_value ?? 50;
  const tolerance = checkIn.tolerance ?? 5;

  const midpoint = Math.round((min + max) / 2);
  const [value, setValue] = useState(midpoint);
  const [submitted, setSubmitted] = useState(false);
  const [isCorrect, setIsCorrect] = useState(false);
  const [hintShown, setHintShown] = useState(false);

  const handleSubmit = useCallback(() => {
    if (submitted) return;

    const withinTolerance = Math.abs(value - correct) <= tolerance;
    setSubmitted(true);
    setIsCorrect(withinTolerance);

    if (withinTolerance) {
      playTTS(checkIn.success_message);
    } else {
      setHintShown(true);
      playTTS(checkIn.hint);
    }
  }, [submitted, value, correct, tolerance, checkIn]);

  const handleRetry = useCallback(() => {
    setSubmitted(false);
    setIsCorrect(false);
  }, []);

  const handleComplete = useCallback(() => {
    onComplete({
      wrongCount: isCorrect ? 0 : 1,
      hintsShown: hintShown ? 1 : 0,
      autoRevealed: 0,
      confusedPairs: isCorrect ? [] : [{
        left: checkIn.instruction,
        right: String(correct),
        wrongCount: 1,
        wrongPicks: [String(value)],
      }],
    });
  }, [isCorrect, hintShown, checkIn.instruction, correct, value, onComplete]);

  // After reveal of correct answer, auto-complete
  const handleAccept = useCallback(() => {
    handleComplete();
  }, [handleComplete]);

  return (
    <div className="checkin-activity">
      <div className="checkin-instruction">{checkIn.instruction}</div>

      <div className="slider-container">
        <div className="slider-labels">
          <span>{min}</span>
          <span>{max}</span>
        </div>
        <input
          type="range"
          className="estimation-slider"
          min={min}
          max={max}
          value={value}
          onChange={e => !submitted && setValue(Number(e.target.value))}
          disabled={submitted}
        />
        <div className="slider-value">{value}</div>
      </div>

      {!submitted && (
        <button className="checkin-continue-btn" onClick={handleSubmit} type="button">
          Lock in!
        </button>
      )}

      {submitted && !isCorrect && (
        <>
          <div className="checkin-hint">
            {checkIn.hint} The answer is {correct}.
          </div>
          <button className="checkin-continue-btn" onClick={handleAccept} type="button">
            Got it!
          </button>
        </>
      )}

      {submitted && isCorrect && (
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
