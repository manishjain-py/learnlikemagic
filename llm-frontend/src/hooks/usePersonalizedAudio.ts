/**
 * usePersonalizedAudio — runtime TTS for cards flagged includes_student_name.
 *
 * Cards flagged `includes_student_name` skip pre-rendered audio (their text
 * contains a `{student_name}` placeholder — the synth has to happen after
 * placeholder substitution). At session start we synthesize all such lines
 * up front, with a concurrency cap, and stash each blob under a synthetic
 * key (`personalized:{card_id}:{line_idx}`) the playback path resolves to
 * a `blob:` URL.
 *
 * Failures degrade to text-only display per PRD §12.
 */
import { useEffect } from 'react';
import { synthesizeSpeech, type DialogueCard, type Personalization } from '../api';
import { attachClientAudioBlob } from './audioController';

const MAX_CONCURRENT_TTS = 4;

export function personalizedAudioKey(cardId: string, lineIdx: number): string {
  return `personalized:${cardId}:${lineIdx}`;
}

function materializeText(text: string, p: Personalization): string {
  const name = (p.student_name || '').trim() || p.fallback_student_name || 'friend';
  return text
    .replaceAll('{student_name}', name)
    .replaceAll('{topic_name}', p.topic_name);
}

async function withConcurrencyLimit(
  tasks: Array<() => Promise<void>>,
  limit: number,
): Promise<void> {
  const executing = new Set<Promise<void>>();
  for (const task of tasks) {
    const p = task().finally(() => {
      executing.delete(p);
    });
    executing.add(p);
    if (executing.size >= limit) {
      await Promise.race(executing);
    }
  }
  await Promise.allSettled(executing);
}

export function usePersonalizedAudio(
  cards: DialogueCard[] | null | undefined,
  personalization: Personalization | null | undefined,
  language: string = 'hinglish',
): void {
  useEffect(() => {
    if (!cards || cards.length === 0 || !personalization) return;
    const personalized = cards.filter((c) => c.includes_student_name);
    if (personalized.length === 0) return;

    let cancelled = false;
    const tasks: Array<() => Promise<void>> = [];
    for (const card of personalized) {
      const cardId = card.card_id;
      if (!cardId) continue;
      card.lines.forEach((line, lineIdx) => {
        tasks.push(async () => {
          if (cancelled) return;
          const text = materializeText(line.audio || '', personalization);
          if (!text.trim()) return;
          try {
            const blob = await synthesizeSpeech(text, language, {
              voiceRole: card.speaker === 'peer' ? 'peer' : 'tutor',
            });
            if (!cancelled) {
              attachClientAudioBlob(personalizedAudioKey(cardId, lineIdx), blob);
            }
          } catch (err) {
            console.warn(
              `Personalized TTS failed for card ${cardId} line ${lineIdx}`,
              err,
            );
          }
        });
      });
    }

    void withConcurrencyLimit(tasks, MAX_CONCURRENT_TTS);
    return () => {
      cancelled = true;
    };
    // Re-run only when the deck or substitution values change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    cards,
    personalization?.student_name,
    personalization?.fallback_student_name,
    personalization?.topic_name,
    language,
  ]);
}
