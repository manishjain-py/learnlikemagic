import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';

interface TypewriterMarkdownProps {
  content: string;
  title?: string;
  isActive: boolean;
  skipAnimation: boolean;
  onRevealComplete?: () => void;
  /** Fires when a block starts typing — use to pre-fetch audio */
  onBlockStart?: (blockText: string, blockIdx: number) => void;
  /** Fires when a block finishes typing — return a Promise that resolves when audio ends */
  onBlockTyped?: (blockText: string, blockIdx: number) => Promise<void>;
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
  onRevealComplete,
  onBlockStart,
  onBlockTyped,
}: TypewriterMarkdownProps) {
  const blocks = useMemo(() => parseBlocks(title, content), [title, content]);
  const fullMarkdown = useMemo(() => joinBlocks(blocks), [blocks]);

  const [activeIdx, setActiveIdx] = useState(0);
  const [phase, setPhase] = useState<'typing' | 'speaking' | 'transitioning'>('typing');
  const [wrapped, setWrapped] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [started, setStarted] = useState(false);

  const spotlightRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const wordSpansRef = useRef<HTMLSpanElement[]>([]);
  const sentenceEnds = useRef<Set<number>>(new Set());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef(false);
  const revealIdx = useRef(0);

  // Stable refs for callbacks to avoid re-triggering effects
  const onBlockStartRef = useRef(onBlockStart);
  onBlockStartRef.current = onBlockStart;
  const onBlockTypedRef = useRef(onBlockTyped);
  onBlockTypedRef.current = onBlockTyped;

  const clearTimer = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  }, []);

  const completeAll = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    clearTimer();
    setCompleted(true);
    onRevealComplete?.();
  }, [clearTimer, onRevealComplete]);

  // Start when first activated
  useEffect(() => {
    if (isActive && !started && !skipAnimation && !completedRef.current) {
      setStarted(true);
    }
  }, [isActive, started, skipAnimation]);

  // Skip or lose focus → complete immediately
  useEffect(() => {
    if (started && !completedRef.current && (skipAnimation || !isActive)) {
      completeAll();
    }
  }, [started, skipAnimation, isActive, completeAll]);

  // Wrap text nodes after ReactMarkdown renders each new block
  useEffect(() => {
    if (!started || completedRef.current || activeIdx >= blocks.length) return;

    const el = contentRef.current;
    if (!el) return;

    wordSpansRef.current = [];
    sentenceEnds.current.clear();
    revealIdx.current = 0;
    setWrapped(false);

    let cancelled = false;
    requestAnimationFrame(() => {
      if (cancelled || !contentRef.current) return;

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
      setWrapped(true);
    });

    return () => { cancelled = true; };
  }, [started, activeIdx, blocks.length]);

  // Typing: reveal words one by one
  useEffect(() => {
    if (!started || completedRef.current || !wrapped || phase !== 'typing' || !isActive) return;

    const spans = wordSpansRef.current;
    const total = spans.length;

    // Notify parent that this block is starting (for audio pre-fetch)
    onBlockStartRef.current?.(blocks[activeIdx].raw, activeIdx);

    if (total === 0) { setPhase('speaking'); return; }

    let idx = revealIdx.current;

    const revealNext = () => {
      if (idx >= total) { setPhase('speaking'); return; }

      spans[idx]?.classList.remove('tw-hidden');
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
      onBlockTypedRef.current(blocks[activeIdx].raw, activeIdx)
        .then(() => {
          if (!cancelled && !completedRef.current) setPhase('transitioning');
        })
        .catch(() => {
          if (!cancelled && !completedRef.current) setPhase('transitioning');
        });
      return () => { cancelled = true; };
    } else {
      // Fallback: hold for HOLD_DURATION when no audio callback
      timerRef.current = setTimeout(() => setPhase('transitioning'), HOLD_DURATION);
      return clearTimer;
    }
  }, [phase, started, clearTimer, blocks, activeIdx]);

  // Transitioning: after animation, advance to next block
  useEffect(() => {
    if (phase !== 'transitioning' || !started || completedRef.current) return;

    timerRef.current = setTimeout(() => {
      const next = activeIdx + 1;
      if (next >= blocks.length) {
        completeAll();
      } else {
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
