/**
 * PersonalitySliders — Binary choice pairs for Section 7.
 */

import React from 'react';
import { PersonalityTrait } from '../../api';

const TRAIT_PAIRS: { trait: string; left: string; leftValue: string; right: string; rightValue: string }[] = [
  { trait: 'warmth', left: 'Takes time to warm up', leftValue: 'reserved', right: 'Outgoing right away', rightValue: 'outgoing' },
  { trait: 'pace', left: 'Likes to take their time', leftValue: 'slow', right: 'Likes to go fast', rightValue: 'fast' },
  { trait: 'curiosity', left: 'Asks lots of questions', leftValue: 'questioning', right: 'Figures things out quietly', rightValue: 'independent' },
  { trait: 'patience', left: 'Gets frustrated easily', leftValue: 'impatient', right: 'Patient and persistent', rightValue: 'patient' },
  { trait: 'variety', left: 'Loves routine and predictability', leftValue: 'routine', right: 'Loves surprises and variety', rightValue: 'variety' },
];

interface PersonalitySlidersProps {
  traits: PersonalityTrait[];
  onChange: (traits: PersonalityTrait[]) => void;
}

export default function PersonalitySliders({ traits, onChange }: PersonalitySlidersProps) {
  const getValue = (traitName: string): string | null => {
    const found = traits.find((t) => t.trait === traitName);
    return found ? found.value : null;
  };

  const setValue = (traitName: string, value: string) => {
    const existing = traits.filter((t) => t.trait !== traitName);
    onChange([...existing, { trait: traitName, value }]);
  };

  return (
    <div className="enrichment-sliders">
      {TRAIT_PAIRS.map((pair) => {
        const current = getValue(pair.trait);
        return (
          <div key={pair.trait} className="enrichment-slider-pair">
            <button
              type="button"
              className={`enrichment-slider-option ${current === pair.leftValue ? 'enrichment-slider-selected' : ''}`}
              onClick={() => setValue(pair.trait, pair.leftValue)}
            >
              {pair.left}
            </button>
            <button
              type="button"
              className={`enrichment-slider-option ${current === pair.rightValue ? 'enrichment-slider-selected' : ''}`}
              onClick={() => setValue(pair.trait, pair.rightValue)}
            >
              {pair.right}
            </button>
          </div>
        );
      })}
    </div>
  );
}
