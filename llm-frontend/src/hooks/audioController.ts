// Global audio control: stop registry + blob prefetch cache.
//
// Stop registry — multiple playback paths (teacher audio, per-line typewriter,
// check-in hook) all register their stop fn here. stopAllAudio() pauses them
// all at once. Called on a new playback, on slide change, and on option taps.
//
// Blob cache — S3 MP3 fetches from us-east-1 cost ~800ms per clip. Activities
// call prefetchAudio(url) on mount so the blob is already in hand by the time
// the student taps. useCheckInAudio / playTeacherAudio read from the cache
// before falling back to a live fetch.

// ─── Stop registry ────────────────────────────────────────────────────────

const stopFns = new Set<() => void>();

export function registerAudioStop(fn: () => void): () => void {
  stopFns.add(fn);
  return () => {
    stopFns.delete(fn);
  };
}

export function stopAllAudio(): void {
  const snapshot = [...stopFns];
  stopFns.clear();
  for (const fn of snapshot) {
    try {
      fn();
    } catch {
      // stop fns should be idempotent
    }
  }
}

// ─── Blob prefetch cache ─────────────────────────────────────────────────

// Map of S3 URL → promise resolving to the MP3 blob. Failed fetches are
// evicted so a later retry can happen.
const blobCache = new Map<string, Promise<Blob>>();

// Cap to keep memory in check on long sessions.
const MAX_CACHE_ENTRIES = 60;

function evictOldest(): void {
  if (blobCache.size <= MAX_CACHE_ENTRIES) return;
  const firstKey = blobCache.keys().next().value;
  if (firstKey !== undefined) blobCache.delete(firstKey);
}

export function prefetchAudio(url: string | undefined | null): void {
  if (!url) return;
  if (blobCache.has(url)) return;
  evictOldest();
  const p = fetch(url)
    .then((res) => {
      if (!res.ok) throw new Error(`S3 ${res.status}`);
      return res.blob();
    })
    .catch((err) => {
      blobCache.delete(url);
      throw err;
    });
  blobCache.set(url, p);
}

export function getCachedBlob(url: string | undefined | null): Promise<Blob> | null {
  if (!url) return null;
  return blobCache.get(url) ?? null;
}

// ─── Synthetic-key blobs (runtime TTS for personalized cards) ────────────
//
// usePersonalizedAudio synthesizes audio for cards flagged
// `includes_student_name` at session start (the student's actual name has to
// be substituted into the placeholder before TTS). Those blobs are stored
// here under a synthetic key (`personalized:{card_id}:{line_idx}`) and the
// playback path resolves the synthetic key to a `blob:` URL it can play.

const clientBlobs = new Map<string, Blob>();

export function attachClientAudioBlob(syntheticKey: string, blob: Blob): void {
  clientBlobs.set(syntheticKey, blob);
}

export function getClientAudioBlob(syntheticKey: string): Blob | null {
  return clientBlobs.get(syntheticKey) ?? null;
}

export function clearClientAudioBlobs(): void {
  clientBlobs.clear();
}

// ─── Global unlocked audio element ────────────────────────────────────────
//
// iOS WebKit (Safari + iOS Chrome, which is required to use WebKit by App
// Store rules) only allows audio.play() outside a user gesture if the audio
// element was previously activated inside one. Fresh `new Audio()` elements
// created mid-session are NOT activated, so .play() rejects with
// NotAllowedError after the gesture window closes. With our `.catch(done)`
// pattern this looks like silent advancement — exactly the iOS Chrome bug
// where only the first dialogue line played.
//
// Fix: every playback path uses ONE module-scope element that we "unlock"
// on the very first user tap by playing a silent WAV. Once unlocked, any
// subsequent .play() on this element succeeds even from purely programmatic
// code paths. Android Chrome (Blink) is more permissive so the bug doesn't
// reproduce there, but the unlock is harmless on every browser.

let _globalAudio: HTMLAudioElement | null = null;
let _audioUnlocked = false;
const SILENT_WAV =
  'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';

export function getGlobalAudio(): HTMLAudioElement {
  if (!_globalAudio) _globalAudio = new Audio();
  return _globalAudio;
}

function _unlockAudio(): void {
  if (_audioUnlocked) return;
  const audio = getGlobalAudio();
  audio.src = SILENT_WAV;
  audio.volume = 0;
  const p = audio.play();
  if (p) {
    p.then(() => {
      audio.pause();
      audio.volume = 1;
      audio.currentTime = 0;
      _audioUnlocked = true;
    }).catch(() => {
      /* try again on next tap */
    });
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('click', _unlockAudio);
  document.addEventListener('touchstart', _unlockAudio);
  document.addEventListener('touchend', _unlockAudio);
}
