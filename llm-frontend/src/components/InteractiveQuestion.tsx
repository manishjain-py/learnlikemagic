import React, { useState, useRef } from 'react';
import { QuestionFormat, BlankItem, OptionItem } from '../api';

interface InteractiveQuestionProps {
  questionFormat: QuestionFormat;
  onSubmit: (answerText: string) => void;
  disabled?: boolean;
  onStartRecording?: () => void;
  onStopRecording?: () => void;
  isRecording?: boolean;
  isTranscribing?: boolean;
  transcribedText?: string;
}

// ─── Fill-in-the-Blank ─────────────────────────────

function FillInTheBlank({
  template,
  blanks,
  onSubmit,
}: {
  template: string;
  blanks: BlankItem[];
  onSubmit: (text: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [activeBlank, setActiveBlank] = useState<number | null>(null);
  const [popupValue, setPopupValue] = useState('');
  const popupInputRef = useRef<HTMLInputElement>(null);

  const allFilled = blanks.every((b) => answers[b.blank_id]?.trim());

  const openBlank = (blankId: number) => {
    setActiveBlank(blankId);
    setPopupValue(answers[blankId] || '');
    setTimeout(() => popupInputRef.current?.focus(), 50);
  };

  const closeBlank = () => {
    if (activeBlank !== null && popupValue.trim()) {
      setAnswers((prev) => ({ ...prev, [activeBlank]: popupValue.trim() }));
    }
    setActiveBlank(null);
    setPopupValue('');
  };

  const handleSubmit = () => {
    let result = template;
    blanks.forEach((b) => {
      result = result.replace(`___${b.blank_id}___`, answers[b.blank_id] || '___');
    });
    onSubmit(result);
  };

  // Parse template into segments: text and blanks
  const segments: Array<{ type: 'text'; value: string } | { type: 'blank'; blankId: number }> = [];
  const regex = /___(\d+)___/g;
  let lastIdx = 0;
  let match;
  while ((match = regex.exec(template)) !== null) {
    if (match.index > lastIdx) {
      segments.push({ type: 'text', value: template.slice(lastIdx, match.index) });
    }
    segments.push({ type: 'blank', blankId: parseInt(match[1], 10) });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < template.length) {
    segments.push({ type: 'text', value: template.slice(lastIdx) });
  }

  return (
    <div className="iq-fill-blank">
      <div className="iq-template-text">
        {segments.map((seg, i) =>
          seg.type === 'text' ? (
            <span key={i}>{seg.value}</span>
          ) : (
            <button
              key={i}
              className={`iq-blank-chip ${answers[seg.blankId] ? 'filled' : 'empty'}`}
              onClick={() => openBlank(seg.blankId)}
              type="button"
            >
              {answers[seg.blankId] || 'tap to fill'}
            </button>
          ),
        )}
      </div>

      {activeBlank !== null && (
        <div className="iq-popup-overlay" onClick={closeBlank}>
          <div className="iq-popup" onClick={(e) => e.stopPropagation()}>
            <div className="iq-popup-label">Fill in blank {activeBlank + 1}</div>
            <input
              ref={popupInputRef}
              className="iq-popup-input"
              type="text"
              value={popupValue}
              onChange={(e) => setPopupValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') closeBlank(); }}
              placeholder="Type your answer..."
            />
            <button className="iq-popup-done" onClick={closeBlank} type="button">
              Done
            </button>
          </div>
        </div>
      )}

      <div className="iq-actions">
        <button
          className="iq-submit-btn"
          disabled={!allFilled}
          onClick={handleSubmit}
          type="button"
        >
          Check my answers
        </button>
        {!allFilled && (
          <button
            className="iq-stuck-btn"
            onClick={handleSubmit}
            type="button"
          >
            I'm stuck
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Single / Multi Select ─────────────────────────

function SelectOptions({
  options,
  multi,
  onSubmit,
}: {
  options: OptionItem[];
  multi: boolean;
  onSubmit: (text: string) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (multi) {
        if (next.has(key)) next.delete(key);
        else next.add(key);
      } else {
        next.clear();
        next.add(key);
      }
      return next;
    });
  };

  const handleSubmit = () => {
    const selectedOptions = options.filter((o) => selected.has(o.key));
    const text = selectedOptions.map((o) => o.text).join(', ');
    onSubmit(text);
  };

  return (
    <div className="iq-select">
      <div className="iq-options">
        {options.map((opt) => (
          <button
            key={opt.key}
            className={`iq-option-chip ${selected.has(opt.key) ? 'selected' : ''}`}
            onClick={() => toggle(opt.key)}
            type="button"
          >
            <span className="iq-option-key">{opt.key}.</span> {opt.text}
          </button>
        ))}
      </div>
      <div className="iq-actions">
        <button
          className="iq-submit-btn"
          disabled={selected.size === 0}
          onClick={handleSubmit}
          type="button"
        >
          Check my answer{multi ? 's' : ''}
        </button>
      </div>
    </div>
  );
}

// ─── Acknowledge (quick-tap continue) ─────────────

function AcknowledgeButtons({ onSubmit }: { onSubmit: (text: string) => void }) {
  return (
    <div className="iq-select">
      <div className="iq-options">
        <button
          className="iq-option-chip"
          onClick={() => onSubmit('OK, got it!')}
          type="button"
        >
          OK, got it!
        </button>
        <button
          className="iq-option-chip"
          onClick={() => onSubmit('Explain more')}
          type="button"
        >
          Explain more
        </button>
      </div>
    </div>
  );
}

// ─── Main Component ────────────────────────────────

export default function InteractiveQuestion({ questionFormat, onSubmit, disabled }: InteractiveQuestionProps) {
  if (disabled) return null;

  if (questionFormat.type === 'acknowledge') {
    return <AcknowledgeButtons onSubmit={onSubmit} />;
  }

  if (questionFormat.type === 'fill_in_the_blank' && questionFormat.sentence_template && questionFormat.blanks) {
    return (
      <FillInTheBlank
        template={questionFormat.sentence_template}
        blanks={questionFormat.blanks}
        onSubmit={onSubmit}
      />
    );
  }

  if (questionFormat.type === 'single_select' && questionFormat.options) {
    return (
      <SelectOptions
        options={questionFormat.options}
        multi={false}
        onSubmit={onSubmit}
      />
    );
  }

  if (questionFormat.type === 'multi_select' && questionFormat.options) {
    return (
      <SelectOptions
        options={questionFormat.options}
        multi={true}
        onSubmit={onSubmit}
      />
    );
  }

  return null;
}
