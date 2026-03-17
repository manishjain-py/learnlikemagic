import React from 'react';

interface ExplanationCard {
  card_idx: number;
  card_type: 'concept' | 'example' | 'visual' | 'analogy' | 'summary';
  title: string;
  content: string;
  visual?: string | null;
}

interface ExplanationViewerProps {
  cards: ExplanationCard[];
  currentIdx: number;
  onNext: () => void;
  onPrevious: () => void;
  onClear: () => void;
  onExplainDifferently: () => void;
  availableVariants: number;
  variantsShown: number;
  loading?: boolean;
}

const CARD_TYPE_LABELS: Record<string, { label: string; icon: string }> = {
  concept: { label: 'Concept', icon: '💡' },
  example: { label: 'Example', icon: '📝' },
  visual: { label: 'Visual', icon: '📊' },
  analogy: { label: 'Analogy', icon: '🔗' },
  summary: { label: 'Summary', icon: '✅' },
};

export default function ExplanationViewer({
  cards,
  currentIdx,
  onNext,
  onPrevious,
  onClear,
  onExplainDifferently,
  availableVariants,
  variantsShown,
  loading,
}: ExplanationViewerProps) {
  const card = cards[currentIdx];
  const isFirst = currentIdx === 0;
  const isLast = currentIdx === cards.length - 1;
  const typeInfo = CARD_TYPE_LABELS[card?.card_type] || { label: card?.card_type, icon: '📄' };

  if (!card) return null;

  return (
    <div className="explanation-viewer">
      {/* Progress bar */}
      <div className="explanation-progress">
        <div className="explanation-progress-bar">
          <div
            className="explanation-progress-fill"
            style={{ width: `${((currentIdx + 1) / cards.length) * 100}%` }}
          />
        </div>
        <span className="explanation-progress-text">
          {currentIdx + 1} of {cards.length}
        </span>
      </div>

      {/* Card */}
      <div className="explanation-card">
        <div className="explanation-card-type">
          <span>{typeInfo.icon} {typeInfo.label}</span>
        </div>
        <h2 className="explanation-card-title">{card.title}</h2>
        <div className="explanation-card-content">
          {card.content.split('\n').map((line, i) => (
            <p key={i}>
              {line.split(/(\*\*.*?\*\*)/g).map((part, j) =>
                part.startsWith('**') && part.endsWith('**')
                  ? <strong key={j}>{part.slice(2, -2)}</strong>
                  : <span key={j}>{part}</span>
              )}
            </p>
          ))}
        </div>
        {card.visual && (
          <pre className="explanation-card-visual">{card.visual}</pre>
        )}
      </div>

      {/* Navigation */}
      <div className="explanation-nav">
        {!isLast ? (
          <>
            <button
              className="explanation-nav-btn secondary"
              onClick={onPrevious}
              disabled={isFirst}
            >
              Back
            </button>
            <button
              className="explanation-nav-btn primary"
              onClick={onNext}
            >
              Next
            </button>
          </>
        ) : (
          <div className="explanation-actions">
            <button
              className="explanation-nav-btn primary"
              onClick={onClear}
              disabled={loading}
            >
              I understand!
            </button>
            <button
              className="explanation-nav-btn secondary"
              onClick={onExplainDifferently}
              disabled={loading}
            >
              {variantsShown >= availableVariants ? "I still don't get it" : "Explain differently"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
