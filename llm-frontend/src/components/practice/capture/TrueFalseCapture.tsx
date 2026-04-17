import React from 'react';
import OptionButton from '../../shared/OptionButton';
import { CaptureProps, QUESTION_TEXT_STYLE } from './types';

/**
 * True/false judgment on a statement. If `statement` is present in the
 * redacted payload it's shown; otherwise falls back to `question_text`.
 */
export default function TrueFalseCapture({
  questionJson, value, onChange, disabled,
}: CaptureProps<boolean>) {
  const statement = (questionJson.statement as string | undefined)
    ?? (questionJson.question_text as string);

  return (
    <div>
      <div style={QUESTION_TEXT_STYLE}>{statement}</div>
      <OptionButton
        label="True"
        selected={value === true}
        onClick={() => onChange(true)}
        disabled={disabled}
      />
      <OptionButton
        label="False"
        selected={value === false}
        onClick={() => onChange(false)}
        disabled={disabled}
      />
    </div>
  );
}
