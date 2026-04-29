/**
 * SpeakerAvatar — spotlight presenter strip for the active dialogue speaker.
 *
 * Renders a 92px portrait + name + role tag + animated speaking pill. Replaces
 * the earlier 44px chip; spec lives in
 * reports/baatcheet-avatar-mockups/variant-2-spotlight.html.
 *
 * Cross-fade on speaker change is still driven by `key={speaker}`: when the
 * card flips between tutor and peer, React remounts this component and the
 * CSS fade-in transition replays. The speaking pill is gated on the boolean
 * `speaking` prop, which BaatcheetViewer toggles around audio playback — so
 * it stays hidden when audio is muted (no playback → never speaking).
 */
import React from 'react';

interface Props {
  speaker: 'tutor' | 'peer' | null;
  speakerName: string;
  speaking: boolean;
}

const ROLE_TAG: Record<'tutor' | 'peer', string> = {
  tutor: 'Your tutor',
  peer: 'Classmate',
};

export default function SpeakerAvatar({ speaker, speakerName, speaking }: Props) {
  if (!speaker) return null;
  const src = speaker === 'tutor' ? '/avatars/tutor.svg' : '/avatars/peer.svg';
  const role = ROLE_TAG[speaker];
  const nameClass =
    speaker === 'peer'
      ? 'speaker-spotlight__name speaker-spotlight__name--peer'
      : 'speaker-spotlight__name';
  return (
    <div
      className={`speaker-spotlight ${speaking ? 'speaker-spotlight--speaking' : ''}`}
      data-speaker={speaker}
      key={speaker}
      aria-label={`${speakerName} ${speaking ? 'is speaking' : ''}`.trim()}
    >
      <div className="speaker-spotlight__portrait">
        <img src={src} alt={speakerName} draggable={false} />
      </div>
      <div className="speaker-spotlight__meta">
        <p className={nameClass}>{speakerName}</p>
        <p className="speaker-spotlight__role">{role}</p>
        {speaking && (
          <span className="speaker-spotlight__pill" aria-hidden="true">
            <span className="speaker-spotlight__bars">
              <span /><span /><span /><span />
            </span>
            speaking
          </span>
        )}
      </div>
    </div>
  );
}
