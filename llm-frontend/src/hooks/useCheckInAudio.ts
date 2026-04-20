import { useRef, useEffect, useCallback } from 'react';
import { synthesizeSpeech } from '../api';
import {
  registerAudioStop,
  stopAllAudio,
  getCachedBlob,
  prefetchAudio,
} from './audioController';

/**
 * Shared TTS playback for check-in activities.
 *
 * Guarantees one audio stream across the whole app: play() calls stopAllAudio()
 * first so any other in-flight track (teacher audio, per-line audio, another
 * check-in hook) is silenced immediately. Unmount stops whatever this instance
 * is playing.
 *
 * When audioUrl is provided and its blob is already in the module-level cache
 * (warmed via prefetchAudio at slide mount), playback is near-instant. Cache
 * miss falls back to a live S3 fetch; S3 failure falls back to synthesizeSpeech.
 */
export function useCheckInAudio() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const tokenRef = useRef(0);
  const unregisterRef = useRef<(() => void) | null>(null);

  const stop = useCallback(() => {
    tokenRef.current += 1; // orphan any in-flight fetch
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    if (unregisterRef.current) {
      unregisterRef.current();
      unregisterRef.current = null;
    }
  }, []);

  const play = useCallback((text: string, audioUrl?: string) => {
    // Silence every other playing track first.
    stopAllAudio();
    stop();
    const token = ++tokenRef.current;

    // 1. Cached blob (prefetched on slide mount) — near-instant.
    // 2. Live S3 fetch — ~800ms from India.
    // 3. Live TTS fallback — ~500ms–1s for short strings.
    let blobPromise: Promise<Blob>;
    if (audioUrl) {
      const cached = getCachedBlob(audioUrl);
      if (cached) {
        blobPromise = cached.catch(() => synthesizeSpeech(text));
      } else {
        // Warm the cache for any future replay of this same clip.
        prefetchAudio(audioUrl);
        blobPromise = (getCachedBlob(audioUrl) ?? fetch(audioUrl).then(r => {
          if (!r.ok) throw new Error(`S3 ${r.status}`);
          return r.blob();
        })).catch(() => synthesizeSpeech(text));
      }
    } else {
      blobPromise = synthesizeSpeech(text);
    }

    blobPromise
      .then((blob) => {
        if (token !== tokenRef.current) return;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        urlRef.current = url;
        unregisterRef.current = registerAudioStop(stop);
        audio.onended = () => {
          if (urlRef.current === url) {
            URL.revokeObjectURL(url);
            urlRef.current = null;
            audioRef.current = null;
            if (unregisterRef.current) {
              unregisterRef.current();
              unregisterRef.current = null;
            }
          }
        };
        audio.play().catch(() => {});
      })
      .catch(() => {});
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { play, stop };
}
