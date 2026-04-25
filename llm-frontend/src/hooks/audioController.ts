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
