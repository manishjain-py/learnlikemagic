/**
 * Shared prop contract for all practice-capture components.
 *
 * Controlled by design:
 *   - `value` is the current student answer (null while unanswered)
 *   - `onChange(next)` is called on every input change
 *   - `seed` deterministically shuffles presentation order (stable on reload)
 *   - `disabled` freezes interaction (used on the review screen)
 *
 * Answer shapes (must match backend grading):
 *   pick_one / fill_blank / tap_to_eliminate / predict_then_reveal /
 *   spot_the_error / odd_one_out → number (original index in questionJson)
 *   true_false → boolean
 *   match_pairs → { [leftText]: rightText }
 *   sort_buckets / swipe_classify → number[] (bucket_idx per item, in served order)
 *   sequence → string[] (ordered sequence items)
 */
export interface CaptureProps<T> {
  questionJson: Record<string, unknown>;
  value: T | null;
  onChange: (value: T) => void;
  seed: number;
  disabled?: boolean;
}
