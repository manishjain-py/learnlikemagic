import React, { useEffect } from 'react';
import { CheckInActivity } from '../api';
import MatchActivity from './MatchActivity';
import PickOneActivity from './PickOneActivity';
import TrueFalseActivity from './TrueFalseActivity';
import FillBlankActivity from './FillBlankActivity';
import SortBucketsActivity from './SortBucketsActivity';
import SequenceActivity from './SequenceActivity';
import SpotTheErrorActivity from './SpotTheErrorActivity';
import OddOneOutActivity from './OddOneOutActivity';
import PredictRevealActivity from './PredictRevealActivity';
import SwipeClassifyActivity from './SwipeClassifyActivity';
import TapToEliminateActivity from './TapToEliminateActivity';
import { stopAllAudio, prefetchAudio } from '../hooks/audioController';

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
  // Warm the blob cache for every TTS URL this check-in can play. By the time
  // the student reads the instruction and taps an option, hint/success blobs
  // are already downloaded, so playback is near-instant instead of ~800ms.
  useEffect(() => {
    prefetchAudio(checkIn.audio_text_url);
    prefetchAudio(checkIn.hint_audio_url);
    prefetchAudio(checkIn.success_audio_url);
    prefetchAudio(checkIn.reveal_audio_url);
  }, [checkIn.audio_text_url, checkIn.hint_audio_url, checkIn.success_audio_url, checkIn.reveal_audio_url]);

  const inner = (() => {
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
      case 'spot_the_error':
        return <SpotTheErrorActivity checkIn={checkIn} onComplete={onComplete} />;
      case 'odd_one_out':
        return <OddOneOutActivity checkIn={checkIn} onComplete={onComplete} />;
      case 'predict_then_reveal':
        return <PredictRevealActivity checkIn={checkIn} onComplete={onComplete} />;
      case 'swipe_classify':
        return <SwipeClassifyActivity checkIn={checkIn} onComplete={onComplete} />;
      case 'tap_to_eliminate':
        return <TapToEliminateActivity checkIn={checkIn} onComplete={onComplete} />;
      case 'match_pairs':
      default:
        return <MatchActivity checkIn={checkIn} onComplete={onComplete} />;
    }
  })();

  // Capture-phase pointer-down silences any ongoing audio before the child's
  // onClick handler runs. This covers options, items, buckets, tap buttons —
  // anything the student interacts with inside the activity. If the child
  // handler then starts new audio (hint/success), it will play normally; if
  // not (e.g. repeat wrong tap after hint already shown), the prior audio
  // still stops on the user's action, which is what they expect.
  return (
    <div onPointerDownCapture={stopAllAudio}>
      {inner}
    </div>
  );
}
