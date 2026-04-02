import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

interface TypewriterMarkdownProps {
  content: string;
  /** Whether this slide is currently visible */
  isActive: boolean;
  /** Skip animation — show all content immediately */
  skipAnimation: boolean;
  /** Called when the full content has been revealed */
  onRevealComplete?: () => void;
}

// Timing constants (ms)
const WORD_DELAY = 400;
const SENTENCE_PAUSE = 600;
const PARAGRAPH_PAUSE = 400;

/**
 * Renders markdown content with a word-by-word typewriter reveal effect.
 *
 * Approach: render the full markdown via ReactMarkdown, then walk the DOM
 * text nodes, wrap each word in a <span>, and progressively reveal them
 * by toggling a CSS class. This preserves all markdown formatting (bold,
 * lists, headings, etc.) while animating the text.
 */
export default function TypewriterMarkdown({
  content,
  isActive,
  skipAnimation,
  onRevealComplete,
}: TypewriterMarkdownProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wordSpansRef = useRef<HTMLSpanElement[]>([]);
  const sentenceEndIndices = useRef<Set<number>>(new Set());
  const paragraphEndIndices = useRef<Set<number>>(new Set());
  const [revealedCount, setRevealedCount] = useState(0);
  const [totalWords, setTotalWords] = useState(0);
  const [wrapped, setWrapped] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef(false);
  const prevActiveRef = useRef(isActive);

  // Wrap text nodes in spans after ReactMarkdown renders
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Reset
    wordSpansRef.current = [];
    sentenceEndIndices.current.clear();
    paragraphEndIndices.current.clear();
    completedRef.current = false;

    const spans: HTMLSpanElement[] = [];

    // Collect all text nodes
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes: Text[] = [];
    while (walker.nextNode()) {
      textNodes.push(walker.currentNode as Text);
    }

    textNodes.forEach((textNode) => {
      const text = textNode.textContent || '';
      if (!text.trim()) return; // skip whitespace-only nodes

      const parent = textNode.parentNode;
      if (!parent) return;

      // Split into words and whitespace, keeping whitespace tokens
      const tokens = text.split(/(\s+)/);
      const fragment = document.createDocumentFragment();

      tokens.forEach((token) => {
        if (/^\s+$/.test(token)) {
          // Whitespace — keep as-is
          fragment.appendChild(document.createTextNode(token));
        } else if (token) {
          const span = document.createElement('span');
          span.textContent = token;
          span.className = 'tw-word tw-hidden';
          spans.push(span);

          // Detect sentence end
          if (/[.!?:]\s*$/.test(token)) {
            sentenceEndIndices.current.add(spans.length - 1);
          }

          fragment.appendChild(span);
        }
      });

      // Check if this text node's block parent ends here (paragraph boundary)
      const blockParent = findBlockParent(textNode, container);
      if (blockParent) {
        // If this is the last text node in this block element, mark paragraph end
        const blockTextNodes = getTextNodesIn(blockParent);
        if (blockTextNodes.length > 0 && blockTextNodes[blockTextNodes.length - 1] === textNode) {
          paragraphEndIndices.current.add(spans.length - 1);
        }
      }

      parent.replaceChild(fragment, textNode);
    });

    wordSpansRef.current = spans;
    setTotalWords(spans.length);

    if (skipAnimation) {
      // Show all immediately
      spans.forEach((s) => s.classList.remove('tw-hidden'));
      setRevealedCount(spans.length);
      completedRef.current = true;
      onRevealComplete?.();
    } else {
      setRevealedCount(0);
    }

    setWrapped(true);
  }, [content]); // Re-run only when content changes

  // Auto-complete reveal when slide loses focus mid-animation
  useEffect(() => {
    if (prevActiveRef.current && !isActive && wrapped && !completedRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current);
      wordSpansRef.current.forEach((s) => s.classList.remove('tw-hidden'));
      setRevealedCount(wordSpansRef.current.length);
      completedRef.current = true;
      onRevealComplete?.();
    }
    prevActiveRef.current = isActive;
  }, [isActive, wrapped, onRevealComplete]);

  // Handle skipAnimation changing after mount (e.g. user taps to skip)
  useEffect(() => {
    if (skipAnimation && wrapped && !completedRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current);
      wordSpansRef.current.forEach((s) => s.classList.remove('tw-hidden'));
      setRevealedCount(wordSpansRef.current.length);
      completedRef.current = true;
      onRevealComplete?.();
    }
  }, [skipAnimation, wrapped, onRevealComplete]);

  // Word-by-word reveal timer
  useEffect(() => {
    if (!isActive || !wrapped || skipAnimation || totalWords === 0) return;
    if (completedRef.current) return;

    let currentIdx = revealedCount;

    const revealNext = () => {
      if (currentIdx >= totalWords) {
        completedRef.current = true;
        setRevealedCount(totalWords);
        onRevealComplete?.();
        return;
      }

      // Reveal this word
      const span = wordSpansRef.current[currentIdx];
      if (span) span.classList.remove('tw-hidden');
      currentIdx++;
      setRevealedCount(currentIdx);

      // Determine delay for next word
      let delay = WORD_DELAY;
      const prevIdx = currentIdx - 1;
      if (paragraphEndIndices.current.has(prevIdx)) {
        delay += PARAGRAPH_PAUSE + SENTENCE_PAUSE;
      } else if (sentenceEndIndices.current.has(prevIdx)) {
        delay += SENTENCE_PAUSE;
      }

      timerRef.current = setTimeout(revealNext, delay);
    };

    timerRef.current = setTimeout(revealNext, WORD_DELAY);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isActive, wrapped, skipAnimation, totalWords]);

  return (
    <div ref={containerRef} className="typewriter-container">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}

/** Walk up from a node to find the nearest block-level parent within container */
function findBlockParent(node: Node, container: HTMLElement): HTMLElement | null {
  const blockTags = new Set(['P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'DIV', 'TR']);
  let current = node.parentElement;
  while (current && current !== container) {
    if (blockTags.has(current.tagName)) return current;
    current = current.parentElement;
  }
  return null;
}

/** Get all text nodes within an element */
function getTextNodesIn(el: HTMLElement): Text[] {
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  return nodes;
}
