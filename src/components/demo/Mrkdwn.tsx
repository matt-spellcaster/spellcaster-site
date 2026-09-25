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
// boundary (so config.service_accounts stays as it is).
const TOKEN =
  /(`[^`\n]+`)|(<[^<>\n]+>)|(:[a-z0-9_+-]+:)|((?<![\p{L}\p{N}])\*[^*\n]+\*(?![\p{L}\p{N}]))|((?<![\p{L}\p{N}])_[^_\n]+_(?![\p{L}\p{N}]))/gu;

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
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index;
    if (at > last) out.push(unescape(text.slice(last, at)));
    const [token, code, angle, emoji, bold, italic] = m;
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
      out.push(EMOJI[name] ? <span key={k}>{EMOJI[name]}</span> : emoji);
    } else if (bold) {
      out.push(
        <strong key={k} className="text-ink font-semibold">
          {inline(bold.slice(1, -1), k)}
        </strong>,
      );
    } else if (italic) {
      out.push(<em key={k}>{inline(italic.slice(1, -1), k)}</em>);
    } else {
      out.push(token);
    }
    last = at + token.length;
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
