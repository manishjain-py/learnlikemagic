import React from 'react';
import { CheckInActivity } from '../api';
import MatchActivity from './MatchActivity';
import PickOneActivity from './PickOneActivity';
import TrueFalseActivity from './TrueFalseActivity';
import FillBlankActivity from './FillBlankActivity';
import SortBucketsActivity from './SortBucketsActivity';
import SequenceActivity from './SequenceActivity';

// ─── Shared result types used by all activity components ─────────────

export interface PairStruggle {
  left: string;
  right: string;
  wrongCount: number;
  wrongPicks?: string[];
}

export interface CheckInActivityResult {
  wrongCount: number;
  hintsShown: number;
  autoRevealed: number;
  confusedPairs: PairStruggle[];
}

// ─── Dispatcher ──────────────────────────────────────────────────────

interface Props {
  checkIn: CheckInActivity;
  onComplete: (result: CheckInActivityResult) => void;
}

export default function CheckInDispatcher({ checkIn, onComplete }: Props) {
  switch (checkIn.activity_type) {
    case 'pick_one':
      return <PickOneActivity checkIn={checkIn} onComplete={onComplete} />;
    case 'true_false':
      return <TrueFalseActivity checkIn={checkIn} onComplete={onComplete} />;
    case 'fill_blank':
      return <FillBlankActivity checkIn={checkIn} onComplete={onComplete} />;
    case 'sort_buckets':
      return <SortBucketsActivity checkIn={checkIn} onComplete={onComplete} />;
    case 'sequence':
      return <SequenceActivity checkIn={checkIn} onComplete={onComplete} />;
    case 'match_pairs':
    default:
      return <MatchActivity checkIn={checkIn} onComplete={onComplete} />;
  }
}
