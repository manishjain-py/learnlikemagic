import { useRef, useEffect, useCallback } from 'react';
import { synthesizeSpeech } from '../api';

/**
 * Shared TTS playback for check-in activities.
 *
 * Guarantees one audio stream per hook instance: a new `play()` stops the
 * previous audio and invalidates any in-flight fetch, and unmount stops
 * whatever is currently playing. Without this, rapid answer taps or hitting
 * Next mid-sentence would stack Audio objects and play them concurrently.
 */
export function useCheckInAudio() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const tokenRef = useRef(0);

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
  }, []);

  const play = useCallback((text: string) => {
    stop();
    const token = ++tokenRef.current;
    synthesizeSpeech(text)
      .then((blob) => {
        if (token !== tokenRef.current) return;
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        urlRef.current = url;
        audio.onended = () => {
          if (urlRef.current === url) {
            URL.revokeObjectURL(url);
            urlRef.current = null;
            audioRef.current = null;
          }
        };
        audio.play().catch(() => {});
      })
      .catch(() => {});
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { play, stop };
}
