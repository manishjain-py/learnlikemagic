import React, { useState, useMemo, useCallback } from 'react';
import { CheckInActivity, synthesizeSpeech } from '../api';

interface PairStruggle {
  left: string;
  right: string;
  wrongCount: number;
}

export interface MatchActivityResult {
  wrongCount: number;
  hintsShown: number;
  autoRevealed: number;
  confusedPairs: PairStruggle[];
}

interface MatchActivityProps {
  checkIn: CheckInActivity;
  onComplete: (result: MatchActivityResult) => void;
}

/** Play a short TTS string — fire-and-forget, errors silently ignored */
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

const AUTO_REVEAL_THRESHOLD = 5;

/** Fisher-Yates shuffle */
function shuffle(arr: number[]): number[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default function MatchActivity({ checkIn, onComplete }: MatchActivityProps) {
  const pairs = checkIn.pairs;

  // Shuffled indices for right column (stable across re-renders)
  const shuffledRight = useMemo(
    () => shuffle(pairs.map((_, i) => i)),
    [pairs],
  );

  const [selectedLeft, setSelectedLeft] = useState<number | null>(null);
  const [matchedPairs, setMatchedPairs] = useState<Set<number>>(new Set());
  const [wrongAttempts, setWrongAttempts] = useState<Map<number, number>>(new Map());
  const [autoRevealed, setAutoRevealed] = useState<Set<number>>(new Set());
  const [showHint, setShowHint] = useState(false);
  const [shakeRight, setShakeRight] = useState<number | null>(null);
  const [showSuccess, setShowSuccess] = useState(false);
  const [totalWrong, setTotalWrong] = useState(0);
  const [hintCount, setHintCount] = useState(0);

  const allMatched = matchedPairs.size + autoRevealed.size >= pairs.length;

  const handleLeftTap = useCallback((leftIdx: number) => {
    if (matchedPairs.has(leftIdx) || autoRevealed.has(leftIdx)) return;
    setSelectedLeft(leftIdx);
    setShowHint(false);
    setShakeRight(null);
  }, [matchedPairs, autoRevealed]);

  const handleRightTap = useCallback((displayIdx: number) => {
    if (selectedLeft === null) return;
    const actualRightIdx = shuffledRight[displayIdx];
    if (matchedPairs.has(actualRightIdx) || autoRevealed.has(actualRightIdx)) return;

    if (actualRightIdx === selectedLeft) {
      // Correct match
      setMatchedPairs(prev => new Set(prev).add(selectedLeft));
      setSelectedLeft(null);
      setShowHint(false);

      // Check if all done
      const newMatched = matchedPairs.size + autoRevealed.size + 1;
      if (newMatched >= pairs.length) {
        setShowSuccess(true);
        playTTS(checkIn.success_message);
      }
    } else {
      // Wrong match
      setTotalWrong(prev => prev + 1);
      const newAttempts = new Map(wrongAttempts);
      const count = (newAttempts.get(selectedLeft) || 0) + 1;
      newAttempts.set(selectedLeft, count);
      setWrongAttempts(newAttempts);

      // Show hint + read aloud
      setShowHint(true);
      setHintCount(prev => prev + 1);
      playTTS(checkIn.hint);

      // Shake animation on wrong right item
      setShakeRight(displayIdx);
      setTimeout(() => setShakeRight(null), 500);

      // Safety valve: auto-reveal after threshold
      if (count >= AUTO_REVEAL_THRESHOLD) {
        setAutoRevealed(prev => new Set(prev).add(selectedLeft));
        setSelectedLeft(null);

        const newTotal = matchedPairs.size + autoRevealed.size + 1;
        if (newTotal >= pairs.length) {
          setShowSuccess(true);
          playTTS(checkIn.success_message);
        }
      }
    }
  }, [selectedLeft, shuffledRight, matchedPairs, autoRevealed, wrongAttempts, pairs.length, checkIn]);

  const handleComplete = useCallback(() => {
    const confusedPairs: PairStruggle[] = [];
    wrongAttempts.forEach((count, leftIdx) => {
      if (count > 0 && leftIdx < pairs.length) {
        confusedPairs.push({
          left: pairs[leftIdx].left,
          right: pairs[leftIdx].right,
          wrongCount: count,
        });
      }
    });
    onComplete({
      wrongCount: totalWrong,
      hintsShown: hintCount,
      autoRevealed: autoRevealed.size,
      confusedPairs,
    });
  }, [wrongAttempts, totalWrong, hintCount, autoRevealed, pairs, onComplete]);

  return (
    <div className="match-activity">
      <div className="match-instruction">{checkIn.instruction}</div>

      <div className="match-columns">
        {/* Left column */}
        <div className="match-column">
          {pairs.map((pair, i) => (
            <button
              key={`left-${i}`}
              className={
                'match-item match-left'
                + (matchedPairs.has(i) ? ' matched' : '')
                + (autoRevealed.has(i) ? ' auto-revealed' : '')
                + (selectedLeft === i ? ' selected' : '')
              }
              onClick={() => handleLeftTap(i)}
              disabled={matchedPairs.has(i) || autoRevealed.has(i)}
              type="button"
            >
              {pair.left}
              {(matchedPairs.has(i) || autoRevealed.has(i)) && <span className="match-check">&#10003;</span>}
            </button>
          ))}
        </div>

        {/* Right column (shuffled) */}
        <div className="match-column">
          {shuffledRight.map((actualIdx, displayIdx) => (
            <button
              key={`right-${displayIdx}`}
              className={
                'match-item match-right'
                + (matchedPairs.has(actualIdx) || autoRevealed.has(actualIdx) ? ' matched' : '')
                + (shakeRight === displayIdx ? ' wrong' : '')
              }
              onClick={() => handleRightTap(displayIdx)}
              disabled={matchedPairs.has(actualIdx) || autoRevealed.has(actualIdx)}
              type="button"
            >
              {pairs[actualIdx].right}
              {(matchedPairs.has(actualIdx) || autoRevealed.has(actualIdx)) && <span className="match-check">&#10003;</span>}
            </button>
          ))}
        </div>
      </div>

      {showHint && !showSuccess && (
        <div className="match-hint">{checkIn.hint}</div>
      )}

      {showSuccess && (
        <div className="match-success">
          <div className="match-success-message">{checkIn.success_message}</div>
          <button className="match-continue-btn" onClick={handleComplete} type="button">
            Continue
          </button>
        </div>
      )}
    </div>
  );
}
