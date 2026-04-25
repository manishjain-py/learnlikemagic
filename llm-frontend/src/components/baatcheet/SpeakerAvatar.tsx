/**
 * SpeakerAvatar — single-character display with cross-fade + speaking pulse.
 *
 * Avatar swap is keyed on `speaker` so React unmounts and remounts the
 * <img>, which re-runs the CSS opacity transition (PRD §FR-36 cross-fade).
 * `speaking` adds a glow ring while audio is playing (PRD §FR-38 placeholder
 * indicator until proper avatars ship in V2).
 */
import React from 'react';

interface Props {
  speaker: 'tutor' | 'peer' | null;
  speaking: boolean;
}

export default function SpeakerAvatar({ speaker, speaking }: Props) {
  if (!speaker) return null;
  const src = speaker === 'tutor' ? '/avatars/tutor.svg' : '/avatars/peer.svg';
  const alt = speaker === 'tutor' ? 'Mr. Verma' : 'Meera';
  return (
    <div
      className={`speaker-avatar ${speaking ? 'speaker-avatar--speaking' : ''}`}
      data-speaker={speaker}
      // key forces React to remount the img on speaker change so the CSS
      // transition replays (cross-fade between turns).
      key={speaker}
    >
      <img src={src} alt={alt} draggable={false} />
      {speaking && <span className="speaker-avatar__pulse" aria-hidden="true" />}
    </div>
  );
}
