import React from 'react';
import PickOneCapture from './capture/PickOneCapture';
import TrueFalseCapture from './capture/TrueFalseCapture';
import FillBlankCapture from './capture/FillBlankCapture';
import TapToEliminateCapture from './capture/TapToEliminateCapture';
import PredictThenRevealCapture from './capture/PredictThenRevealCapture';
import SpotTheErrorCapture from './capture/SpotTheErrorCapture';
import OddOneOutCapture from './capture/OddOneOutCapture';
import MatchPairsCapture from './capture/MatchPairsCapture';
import SortBucketsCapture from './capture/SortBucketsCapture';
import SwipeClassifyCapture from './capture/SwipeClassifyCapture';
import SequenceCapture from './capture/SequenceCapture';
import FreeFormQuestion from './FreeFormQuestion';

interface Props {
  format: string;
  questionJson: Record<string, unknown>;
  value: unknown;
  onChange: (value: unknown) => void;
  seed: number;
  disabled?: boolean;
}

/**
 * Dispatch from `format` string to the right capture component. Runner +
 * review pages both use this — `disabled=true` for the review mode.
 *
 * Each capture has its own per-format `value` type; this component works
 * in `unknown` to stay generic. Callers store the value without needing
 * to know the shape (the backend grader discriminates by format).
 */
export default function QuestionRenderer({
  format, questionJson, value, onChange, seed, disabled,
}: Props) {
  const common = { questionJson, seed, disabled };

  switch (format) {
    case 'pick_one':
      return <PickOneCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'true_false':
      return <TrueFalseCapture {...common} value={value as boolean | null} onChange={onChange} />;
    case 'fill_blank':
      return <FillBlankCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'tap_to_eliminate':
      return <TapToEliminateCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'predict_then_reveal':
      return <PredictThenRevealCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'spot_the_error':
      return <SpotTheErrorCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'odd_one_out':
      return <OddOneOutCapture {...common} value={value as number | null} onChange={onChange} />;
    case 'match_pairs':
      return <MatchPairsCapture {...common} value={value as Record<string, string> | null} onChange={onChange} />;
    case 'sort_buckets':
      return <SortBucketsCapture {...common} value={value as number[] | null} onChange={onChange} />;
    case 'swipe_classify':
      return <SwipeClassifyCapture {...common} value={value as number[] | null} onChange={onChange} />;
    case 'sequence':
      return <SequenceCapture {...common} value={value as string[] | null} onChange={onChange} />;
    case 'free_form':
      return <FreeFormQuestion {...common} value={value as string | null} onChange={onChange} />;
    default:
      return (
        <div className="practice-error">
          Unknown question format: {format}
        </div>
      );
  }
}
