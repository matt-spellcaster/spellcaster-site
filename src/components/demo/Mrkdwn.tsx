// Slack's mrkdwn, as the tool writes it, drawn as React nodes. Never as HTML: every piece of
// text, the reviewer's own reasons included, reaches the page as a text node. A Slack link
// (<url|label>) is drawn as its label only, so nothing inside a simulated frame is a link.

import { Fragment, type ReactNode } from 'react';
import { copy } from './copy';

const EMOJI: Record<string, string> = {
  white_check_mark: '✅',
  no_entry: '⛔',
  warning: '⚠️',
  grey_question: '❔',
  ticket: '🎫',
  clipboard: '📋',
  lock: '🔒',
  page_facing_up: '📄',
  triangular_flag_on_post: '🚩',
  red_circle: '🔴',
  large_orange_circle: '🟠',
  large_yellow_circle: '🟡',
  white_circle: '⚪',
  large_blue_circle: '🔵',
  white_large_square: '⬜',
};

// Code, a <…> token, an :emoji:, then *bold* and _italic_, which Slack only honours at a word
// boundary (so config.service_accounts stays as it is). The boundary before one is checked in
// code, not with a lookbehind, which Safari before 16.4 can't parse at all.
const TOKEN =
  /(`[^`\n]+`)|(<[^<>\n]+>)|(:[a-z0-9_+-]+:)|(\*[^*\n]+\*(?![\p{L}\p{N}]))|(_[^_\n]+_(?![\p{L}\p{N}]))/gu;
const WORD = /[\p{L}\p{N}]/u;

/** Whether the character before index at is a letter or a digit. */
function wordBefore(text: string, at: number): boolean {
  const before = Array.from(text.slice(Math.max(0, at - 2), at)).pop();
  return before !== undefined && WORD.test(before);
}

/** Slack's three escapes, undone for display. */
export function unescape(text: string): string {
  return text.replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');
}

function special(token: string): ReactNode {
  const inner = token.slice(1, -1);
  if (inner.startsWith('@')) return <span className="text-accent font-medium">{copy.ciso}</span>;
  if (inner.startsWith('#')) return <span className="text-accent">#review</span>;
  const bar = inner.indexOf('|');
  return <span className="text-accent">{unescape(bar < 0 ? inner : inner.slice(bar + 1))}</span>;
}

export function inline(text: string, key = 'm'): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  const token = new RegExp(TOKEN); // its own lastIndex: inline() calls itself for bold
  for (let m = token.exec(text); m; m = token.exec(text)) {
    const at = m.index;
    const [whole, code, angle, emoji, bold, italic] = m;
    if ((bold || italic) && wordBefore(text, at)) {
      token.lastIndex = at + 1;
      continue;
    }
    if (at > last) out.push(unescape(text.slice(last, at)));
    const k = `${key}-${n++}`;
    if (code) {
      out.push(
        <code key={k} className="bg-surface-2 rounded px-1 font-mono text-[0.85em] break-all">
          {unescape(code.slice(1, -1))}
        </code>,
      );
    } else if (angle) {
      out.push(<Fragment key={k}>{special(angle)}</Fragment>);
    } else if (emoji) {
      const name = emoji.slice(1, -1);
      // Own names only: a reason can say :__proto__: too.
      out.push(Object.hasOwn(EMOJI, name) ? <span key={k}>{EMOJI[name]}</span> : emoji);
    } else if (bold) {
      out.push(
        <strong key={k} className="text-ink font-semibold">
          {inline(bold.slice(1, -1), k)}
        </strong>,
      );
    } else if (italic) {
      out.push(<em key={k}>{inline(italic.slice(1, -1), k)}</em>);
    } else {
      out.push(whole);
    }
    last = at + whole.length;
  }
  if (last < text.length) out.push(unescape(text.slice(last)));
  return out;
}

/** One mrkdwn text, line breaks kept (the sign-off list indents with spaces). */
export function Mrkdwn({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={`break-words whitespace-pre-wrap ${className}`}>
      {text.split('\n').map((line, i) => (
        <Fragment key={i}>
          {i > 0 && '\n'}
          {inline(line, `l${i}`)}
        </Fragment>
      ))}
    </div>
  );
}
