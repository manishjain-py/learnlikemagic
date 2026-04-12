import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { debugLog } from '../debugLog';

interface AudioLine {
  display: string;
  audio: string;
  audio_url?: string;  // S3 URL for pre-computed TTS MP3
}

interface TypewriterMarkdownProps {
  content: string;
  title?: string;
  isActive: boolean;
  skipAnimation: boolean;
  audioLines?: AudioLine[];  // Per-line LLM-generated audio text
  onRevealComplete?: () => void;
  /** Fires when a block starts typing — use to pre-fetch audio */
  onBlockStart?: (audioText: string, blockIdx: number) => void;
  /** Fires when a block finishes typing — return a Promise that resolves when audio ends */
  onBlockTyped?: (audioText: string, blockIdx: number) => Promise<void>;
}

// Timing constants (ms)
const WORD_DELAY = 400;
const SENTENCE_PAUSE = 600;
const HOLD_DURATION = 1500;
const TRANSITION_DURATION = 900;

type BlockType = 'heading' | 'paragraph' | 'listItem' | 'code';

interface Block {
  raw: string;
  type: BlockType;
}

/** Split markdown into logical blocks — each becomes one spotlight line */
function parseBlocks(title: string | undefined, content: string): Block[] {
  const blocks: Block[] = [];

  if (title?.trim()) {
    blocks.push({ raw: `## ${title.trim()}`, type: 'heading' });
  }

  const lines = content.split('\n');
  let i = 0;

  while (i < lines.length) {
    const trimmed = lines[i].trim();
    if (!trimmed) { i++; continue; }

    // Code block
    if (trimmed.startsWith('```')) {
      let code = lines[i];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code += '\n' + lines[i];
        i++;
      }
      if (i < lines.length) { code += '\n' + lines[i]; i++; }
      blocks.push({ raw: code, type: 'code' });
      continue;
    }

    // Heading
    if (/^#{1,6}\s/.test(trimmed)) {
      blocks.push({ raw: trimmed, type: 'heading' });
      i++; continue;
    }

    // List item
    if (/^[-*+]\s|^\d+\.\s/.test(trimmed)) {
      blocks.push({ raw: trimmed, type: 'listItem' });
      i++; continue;
    }

    // Paragraph — collect consecutive non-special lines
    let para = trimmed;
    i++;
    while (
      i < lines.length && lines[i].trim() &&
      !/^#{1,6}\s/.test(lines[i].trim()) &&
      !/^[-*+]\s|^\d+\.\s/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith('```')
    ) {
      para += ' ' + lines[i].trim();
      i++;
    }
    blocks.push({ raw: para, type: 'paragraph' });
  }

  return blocks;
}

/** Reconstruct markdown from blocks, keeping consecutive list items grouped */
function joinBlocks(blocks: Block[]): string {
  let md = '';
  for (let i = 0; i < blocks.length; i++) {
    if (i > 0) {
      const prevList = blocks[i - 1].type === 'listItem';
      const currList = blocks[i].type === 'listItem';
      md += (prevList && currList) ? '\n' : '\n\n';
    }
    md += blocks[i].raw;
  }
  return md;
}

export default function TypewriterMarkdown({
  content,
  title,
  isActive,
  skipAnimation,
  audioLines,
  onRevealComplete,
  onBlockStart,
  onBlockTyped,
}: TypewriterMarkdownProps) {
  const _tag = `[TW ${(title || content).slice(0, 25)}]`;

  // When audioLines exist, each line is its own block (skip parseBlocks which
  // merges consecutive plain lines into one paragraph). This gives tight
  // line-by-line reveal + audio sync.
  const blocks = useMemo(() => {
    if (audioLines && audioLines.length > 0) {
      const b: Block[] = [];
      if (title?.trim()) {
        b.push({ raw: `## ${title.trim()}`, type: 'heading' });
      }
      for (const line of audioLines) {
        b.push({ raw: line.display, type: 'paragraph' });
      }
      debugLog(`${_tag} blocks built from audioLines: ${b.length} blocks (title=${!!title?.trim()}, audioLines=${audioLines.length})`);
      return b;
    }
    const parsed = parseBlocks(title, content);
    debugLog(`${_tag} blocks built from parseBlocks: ${parsed.length} blocks`);
    return parsed;
  }, [audioLines, title, content]);

  const fullMarkdown = useMemo(() => joinBlocks(blocks), [blocks]);

  // Maps block index → audio text for TTS callbacks
  const blockAudioRef = useRef<Map<number, string>>(new Map());
  useMemo(() => {
    const m = new Map<number, string>();
    if (audioLines && audioLines.length > 0) {
      const offset = title?.trim() ? 1 : 0;
      if (offset) m.set(0, title!.trim());
      audioLines.forEach((line, i) => m.set(i + offset, line.audio));
    }
    blockAudioRef.current = m;
  }, [audioLines, title]);

  const [activeIdx, setActiveIdx] = useState(0);
  const [phase, setPhase] = useState<'typing' | 'speaking' | 'transitioning'>('typing');
  const [wrapped, setWrapped] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [started, setStarted] = useState(false);

  const spotlightRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLSpanElement | null>(null);
  const wordSpansRef = useRef<HTMLSpanElement[]>([]);
  const sentenceEnds = useRef<Set<number>>(new Set());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef(false);
  const revealIdx = useRef(0);

  // Stable refs for callbacks to avoid re-triggering effects.
  // Inline arrow functions from the parent change identity every render.
  // Using refs keeps effect dependency arrays stable.
  const onBlockStartRef = useRef(onBlockStart);
  onBlockStartRef.current = onBlockStart;
  const onBlockTypedRef = useRef(onBlockTyped);
  onBlockTypedRef.current = onBlockTyped;
  const onRevealCompleteRef = useRef(onRevealComplete);
  onRevealCompleteRef.current = onRevealComplete;

  const clearTimer = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  }, []);

  const completeAll = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    clearTimer();
    cursorRef.current?.remove();
    setCompleted(true);
    onRevealCompleteRef.current?.();
  }, [clearTimer]);

  // Start when first activated
  useEffect(() => {
    if (isActive && !started && !skipAnimation && !completedRef.current) {
      debugLog(`${_tag} START — isActive=${isActive}, skipAnimation=${skipAnimation}, blocks=${blocks.length}`);
      setStarted(true);
    }
  }, [isActive, started, skipAnimation]);

  // Skip or lose focus → complete immediately
  useEffect(() => {
    if (started && !completedRef.current && (skipAnimation || !isActive)) {
      debugLog(`${_tag} COMPLETE-ALL — skipAnimation=${skipAnimation}, isActive=${isActive}`);
      completeAll();
    }
  }, [started, skipAnimation, isActive, completeAll]);

  // Wrap text nodes after ReactMarkdown renders each new block
  useEffect(() => {
    if (!started || completedRef.current || activeIdx >= blocks.length) {
      debugLog(`${_tag} WRAP skip — started=${started}, completed=${completedRef.current}, activeIdx=${activeIdx}, blocks=${blocks.length}`);
      return;
    }

    const el = contentRef.current;
    if (!el) {
      debugLog(`${_tag} WRAP skip — contentRef is null`);
      return;
    }

    debugLog(`${_tag} WRAP begin — activeIdx=${activeIdx}, block="${blocks[activeIdx]?.raw.slice(0, 40)}"`);
    wordSpansRef.current = [];
    sentenceEnds.current.clear();
    revealIdx.current = 0;
    setWrapped(false);

    let cancelled = false;
    requestAnimationFrame(() => {
      if (cancelled || !contentRef.current) {
        debugLog(`${_tag} WRAP rAF cancelled — cancelled=${cancelled}, ref=${!!contentRef.current}`);
        return;
      }

      const spans: HTMLSpanElement[] = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const textNodes: Text[] = [];
      while (walker.nextNode()) textNodes.push(walker.currentNode as Text);

      textNodes.forEach((textNode) => {
        const text = textNode.textContent || '';
        if (!text.trim()) return;
        const parent = textNode.parentNode;
        if (!parent) return;

        const tokens = text.split(/(\s+)/);
        const fragment = document.createDocumentFragment();

        tokens.forEach((token) => {
          if (/^\s+$/.test(token)) {
            fragment.appendChild(document.createTextNode(token));
          } else if (token) {
            const span = document.createElement('span');
            span.textContent = token;
            span.className = 'tw-word tw-hidden';
            spans.push(span);
            if (/[.!?:]\s*$/.test(token)) sentenceEnds.current.add(spans.length - 1);
            fragment.appendChild(span);
          }
        });

        parent.replaceChild(fragment, textNode);
      });

      wordSpansRef.current = spans;
      debugLog(`${_tag} WRAP done — ${spans.length} word spans found for activeIdx=${activeIdx}`);
      setWrapped(true);
    });

    return () => { cancelled = true; };
  }, [started, activeIdx, blocks.length]);

  // Typing: reveal words one by one
  useEffect(() => {
    if (!started || completedRef.current || !wrapped || phase !== 'typing' || !isActive) {
      if (phase === 'typing' && started && wrapped) {
        debugLog(`${_tag} TYPING skip — completed=${completedRef.current}, isActive=${isActive}`);
      }
      return;
    }

    const spans = wordSpansRef.current;
    const total = spans.length;

    // Notify parent that this block is starting (for audio pre-fetch).
    // Use LLM-generated audio text when available, fall back to raw block text.
    const audioText = blockAudioRef.current.get(activeIdx) || blocks[activeIdx].raw;
    debugLog(`${_tag} TYPING start — activeIdx=${activeIdx}/${blocks.length}, words=${total}, audioText="${audioText?.slice(0, 40)}..."`);
    onBlockStartRef.current?.(audioText, activeIdx);

    if (total === 0) {
      debugLog(`${_tag} TYPING → SPEAKING (0 words, skipping straight to audio)`);
      setPhase('speaking');
      return;
    }

    // Create cursor element if it doesn't exist
    if (!cursorRef.current) {
      const c = document.createElement('span');
      c.className = 'tw-cursor';
      cursorRef.current = c;
    }
    const cursor = cursorRef.current;

    let idx = revealIdx.current;

    const revealNext = () => {
      if (idx >= total) {
        cursor.remove();
        cursorRef.current = null;
        debugLog(`${_tag} TYPING done → SPEAKING — all ${total} words revealed for activeIdx=${activeIdx}`);
        setPhase('speaking');
        return;
      }

      const span = spans[idx];
      span?.classList.remove('tw-hidden');
      // Move cursor right after the revealed word
      span?.parentNode?.insertBefore(cursor, span.nextSibling);
      idx++;
      revealIdx.current = idx;

      let delay = WORD_DELAY;
      if (sentenceEnds.current.has(idx - 1)) delay += SENTENCE_PAUSE;
      timerRef.current = setTimeout(revealNext, delay);
    };

    timerRef.current = setTimeout(revealNext, WORD_DELAY);
    return clearTimer;
  }, [started, wrapped, phase, isActive, clearTimer, blocks, activeIdx]);

  // Speaking: play audio or hold after line completes
  useEffect(() => {
    if (phase !== 'speaking' || !started || completedRef.current) return;

    if (onBlockTypedRef.current) {
      let cancelled = false;
      const audioText = blockAudioRef.current.get(activeIdx) || blocks[activeIdx].raw;
      debugLog(`${_tag} SPEAKING — calling onBlockTyped for activeIdx=${activeIdx}, audioText="${audioText?.slice(0, 40)}..."`);
      const speakStart = Date.now();
      // Safety: if onBlockTyped never resolves (e.g. audio hangs), force-advance.
      // 15s > playLineAudio's 12s safety timeout, so playLineAudio resolves first
      // in the normal degraded case. This is the outer failsafe.
      const safetyTimer = setTimeout(() => {
        if (!cancelled && !completedRef.current) {
          debugLog(`${_tag} SPEAKING SAFETY TIMEOUT (15s) — forcing transition for activeIdx=${activeIdx}`);
          setPhase('transitioning');
        }
      }, 15_000);
      onBlockTypedRef.current(audioText, activeIdx)
        .then(() => {
          clearTimeout(safetyTimer);
          debugLog(`${_tag} SPEAKING → TRANSITIONING (resolved in ${Date.now() - speakStart}ms) activeIdx=${activeIdx}, cancelled=${cancelled}`);
          if (!cancelled && !completedRef.current) setPhase('transitioning');
        })
        .catch((err) => {
          clearTimeout(safetyTimer);
          debugLog(`${_tag} SPEAKING → TRANSITIONING (rejected in ${Date.now() - speakStart}ms) activeIdx=${activeIdx} — ${err}`);
          if (!cancelled && !completedRef.current) setPhase('transitioning');
        });
      return () => {
        debugLog(`${_tag} SPEAKING cleanup — cancelled=true for activeIdx=${activeIdx}`);
        cancelled = true;
        clearTimeout(safetyTimer);
      };
    } else {
      debugLog(`${_tag} SPEAKING — no onBlockTyped callback, holding for ${HOLD_DURATION}ms`);
      // Fallback: hold for HOLD_DURATION when no audio callback
      timerRef.current = setTimeout(() => setPhase('transitioning'), HOLD_DURATION);
      return clearTimer;
    }
  }, [phase, started, clearTimer, blocks, activeIdx]);

  // Transitioning: after animation, advance to next block
  useEffect(() => {
    if (phase !== 'transitioning' || !started || completedRef.current) return;

    debugLog(`${_tag} TRANSITIONING — activeIdx=${activeIdx}, next=${activeIdx + 1}/${blocks.length}`);
    timerRef.current = setTimeout(() => {
      const next = activeIdx + 1;
      if (next >= blocks.length) {
        debugLog(`${_tag} TRANSITIONING → COMPLETE (all blocks done)`);
        completeAll();
      } else {
        debugLog(`${_tag} TRANSITIONING → TYPING (advancing to block ${next})`);
        setActiveIdx(next);
        setPhase('typing');
        setWrapped(false);
      }
    }, TRANSITION_DURATION);

    return clearTimer;
  }, [phase, started, activeIdx, blocks.length, clearTimer, completeAll]);

  // Auto-scroll spotlight into view (scroll only the .focus-slide ancestor, not the carousel track)
  useEffect(() => {
    if (!started || completedRef.current) return;
    requestAnimationFrame(() => {
      const el = spotlightRef.current;
      if (!el) return;
      let scrollParent: HTMLElement | null = el.parentElement;
      while (scrollParent && !scrollParent.classList.contains('focus-slide')) {
        scrollParent = scrollParent.parentElement;
      }
      if (!scrollParent) return;
      const parentRect = scrollParent.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const scrollTarget = el.offsetTop - (parentRect.height / 2) + (elRect.height / 2);
      scrollParent.scrollTo({ top: Math.max(0, scrollTarget), behavior: 'smooth' });
    });
  }, [started, activeIdx, wrapped]);

  // --- Render ---

  // Before activation or after completion: show full markdown
  if (!started || completed) {
    return (
      <div className="tw-spotlight-container">
        {(completed || skipAnimation) ? (
          <ReactMarkdown>{fullMarkdown}</ReactMarkdown>
        ) : null}
      </div>
    );
  }

  const archivedMd = activeIdx > 0 ? joinBlocks(blocks.slice(0, activeIdx)) : '';
  const isTransitioning = phase === 'transitioning' && activeIdx < blocks.length;

  return (
    <div className="tw-spotlight-container tw-animating">
      {(archivedMd || isTransitioning) && (
        <div className="tw-archive">
          {archivedMd && <ReactMarkdown>{archivedMd}</ReactMarkdown>}
          {isTransitioning && (
            <div className="tw-archive-incoming">
              <ReactMarkdown>{blocks[activeIdx].raw}</ReactMarkdown>
            </div>
          )}
        </div>
      )}

      <div className="tw-spacer" />

      {activeIdx < blocks.length && (
        <div
          ref={spotlightRef}
          className={`tw-spotlight${phase === 'transitioning' ? ' tw-spotlight--transitioning' : ''}${phase === 'speaking' ? ' tw-spotlight--speaking' : ''}`}
        >
          <div ref={contentRef} key={activeIdx} className="tw-spotlight-content">
            <ReactMarkdown>{blocks[activeIdx].raw}</ReactMarkdown>
          </div>
        </div>
      )}

      <div className="tw-spacer" />
    </div>
  );
}
