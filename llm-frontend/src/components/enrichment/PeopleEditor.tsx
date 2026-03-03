/**
 * PeopleEditor — Repeating card for Section 2 (My World).
 * Name + Relationship per entry, max 15.
 */

import React from 'react';
import { MyWorldEntry } from '../../api';

const RELATIONSHIPS = [
  'Mom', 'Dad', 'Brother', 'Sister', 'Grandparent',
  'Cousin', 'Uncle', 'Aunt', 'Friend', 'Neighbor', 'Teacher', 'Pet',
];

interface PeopleEditorProps {
  entries: MyWorldEntry[];
  onChange: (entries: MyWorldEntry[]) => void;
}

export default function PeopleEditor({ entries, onChange }: PeopleEditorProps) {
  const updateEntry = (index: number, field: keyof MyWorldEntry, value: string) => {
    const updated = [...entries];
    updated[index] = { ...updated[index], [field]: value };
    onChange(updated);
  };

  const addEntry = () => {
    if (entries.length >= 15) return;
    onChange([...entries, { name: '', relationship: 'Friend' }]);
  };

  const removeEntry = (index: number) => {
    onChange(entries.filter((_, i) => i !== index));
  };

  return (
    <div className="enrichment-people">
      {entries.map((entry, index) => (
        <div key={index} className="enrichment-person-card">
          <input
            type="text"
            value={entry.name}
            onChange={(e) => updateEntry(index, 'name', e.target.value)}
            placeholder="Name"
            maxLength={50}
            className="enrichment-person-name"
          />
          <select
            value={entry.relationship}
            onChange={(e) => updateEntry(index, 'relationship', e.target.value)}
            className="enrichment-person-rel"
          >
            {RELATIONSHIPS.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <button
            type="button"
            className="enrichment-person-remove"
            onClick={() => removeEntry(index)}
            title="Remove"
          >
            x
          </button>
        </div>
      ))}
      {entries.length < 15 && (
        <button type="button" className="enrichment-add-btn" onClick={addEntry}>
          + Add another
        </button>
      )}
    </div>
  );
}
