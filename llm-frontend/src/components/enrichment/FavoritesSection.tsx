/**
 * FavoritesSection — Section 8: tag inputs + textarea.
 */

import React, { useState } from 'react';

interface FavoritesSectionProps {
  favoriteMedia: string[];
  favoriteCharacters: string[];
  memorableExperience: string;
  aspiration: string;
  onChange: (field: string, value: any) => void;
}

function TagInput({ tags, onChange, placeholder }: { tags: string[]; onChange: (tags: string[]) => void; placeholder: string }) {
  const [input, setInput] = useState('');

  const addTag = () => {
    const trimmed = input.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInput('');
  };

  const removeTag = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTag();
    }
  };

  return (
    <div className="enrichment-tag-input">
      <div className="enrichment-tags">
        {tags.map((tag) => (
          <span key={tag} className="enrichment-tag">
            {tag}
            <button type="button" onClick={() => removeTag(tag)}>x</button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={addTag}
        placeholder={placeholder}
        maxLength={50}
      />
    </div>
  );
}

export default function FavoritesSection({
  favoriteMedia,
  favoriteCharacters,
  memorableExperience,
  aspiration,
  onChange,
}: FavoritesSectionProps) {
  return (
    <div className="enrichment-favorites">
      <div className="auth-field">
        <label>Favorite movies / shows</label>
        <TagInput
          tags={favoriteMedia}
          onChange={(v) => onChange('favorite_media', v)}
          placeholder="Type and press Enter"
        />
      </div>

      <div className="auth-field">
        <label>Favorite books / characters</label>
        <TagInput
          tags={favoriteCharacters}
          onChange={(v) => onChange('favorite_characters', v)}
          placeholder="Type and press Enter"
        />
      </div>

      <div className="auth-field">
        <label>A trip, experience, or story they love to talk about</label>
        <textarea
          value={memorableExperience}
          onChange={(e) => onChange('memorable_experience', e.target.value)}
          placeholder="E.g., 'Our trip to the zoo last summer...'"
          maxLength={500}
          rows={3}
        />
        <span className="enrichment-char-count">{memorableExperience.length}/500</span>
      </div>

      <div className="auth-field">
        <label>What do they want to be when they grow up?</label>
        <input
          type="text"
          value={aspiration}
          onChange={(e) => onChange('aspiration', e.target.value)}
          placeholder="E.g., astronaut, doctor, cricketer..."
          maxLength={200}
        />
        <span className="enrichment-char-count">{aspiration.length}/200</span>
      </div>
    </div>
  );
}
