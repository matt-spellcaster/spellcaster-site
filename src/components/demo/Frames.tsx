// The simulated Slack and Jira frames, and the Slack blocks and Jira documents inside them.

import type { ReactNode } from 'react';
import type { AdfDoc, Block, Button, Item, Severity, SlackPayload } from '../../lib/demo/types';
import { copy } from './copy';
import { inline, Mrkdwn } from './Mrkdwn';

export function Frame({
  badge,
  title,
  children,
}: {
  badge: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={`${badge}: ${title}`}
      className="border-line bg-surface overflow-hidden rounded-xl border font-sans"
    >
      <div className="border-line flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <span className="text-ink text-sm font-medium">{title}</span>
        <span className="border-line text-muted rounded-full border px-2.5 py-0.5 text-xs">
          {badge}
        </span>
      </div>
      <div className="px-4 py-4">{children}</div>
    </section>
  );
}

/** One message from the bot, as Slack lays it out. */
export function Message({ children }: { children: ReactNode }) {
  return (
    <article className="flex gap-3 py-2">
      <div
        aria-hidden="true"
        className="bg-surface-2 text-accent grid size-9 shrink-0 place-items-center rounded-lg text-xs font-semibold"
      >
        AR
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <span className="text-ink font-semibold">{copy.bot}</span>{' '}
          <span className="bg-surface-2 text-muted rounded px-1 text-[0.6875rem]">APP</span>
        </p>
        <div className="text-ink/85 mt-1 space-y-2 text-sm leading-relaxed">{children}</div>
      </div>
    </article>
  );
}

export type OnAction = (button: Button) => void;

const SEVERITY: Record<Severity, string> = {
  critical: 'border-revoke text-revoke',
  high: 'border-revoke text-revoke',
  medium: 'border-decide text-decide',
  low: 'border-line text-muted',
  info: 'border-line text-muted',
};

function Chip({ severity }: { severity: Severity }) {
  return (
    <span
      className={`mr-1.5 inline-block rounded border px-1 align-[0.1em] text-[0.6875rem] leading-4 font-medium uppercase ${SEVERITY[severity]}`}
    >
      {severity}
    </span>
  );
}

/**
 * An item card's text, with each concern's graded severity in place of its warning sign. The
 * card is built as: who, the facts, what this decision doesn't change, why it could be an
 * issue, the proposal (slack_review.card_lines), so the concerns are found by their heading.
 */
function Card({ item }: { item: Item }) {
  const lines = item.render.card.split('\n');
  let list: 'concerns' | 'outside_okta' | null = null;
  let n = 0;
  return (
    <div className="break-words whitespace-pre-wrap">
      {lines.map((line, i) => {
        if (line.startsWith('*Why it could be an issue*')) [list, n] = ['concerns', 0];
        else if (line.startsWith('*Outside this decision*')) [list, n] = ['outside_okta', 0];
        else if (line.startsWith('*')) list = null;
        const warning = '• :warning: ';
        const graded = list && line.startsWith(warning) ? item.render[list][n++] : null;
        return (
          <span key={i}>
            {i > 0 && '\n'}
            {graded ? (
              <>
                {'• '}
                <Chip severity={graded.severity} />
                {inline(line.slice(warning.length), `c${i}`)}
              </>
            ) : (
              inline(line, `c${i}`)
            )}
          </span>
        );
      })}
    </div>
  );
}

const STYLE = {
  primary: 'border-keep text-keep',
  danger: 'border-revoke text-revoke',
  plain: 'border-line text-ink',
};

function Actions({
  elements,
  onAction,
  disabled,
}: {
  elements: Button[];
  onAction?: OnAction | undefined;
  disabled?: boolean | undefined;
}) {
  return (
    <div className="flex flex-wrap gap-2 pt-1">
      {elements.map((b) => (
        <button
          key={b.action_id}
          type="button"
          disabled={disabled || !onAction}
          onClick={() => onAction?.(b)}
          className={`hover:bg-surface-2 min-h-11 rounded-lg border px-4 text-sm font-medium transition-colors disabled:opacity-60 ${STYLE[b.style ?? 'plain']}`}
        >
          {b.text.text}
        </button>
      ))}
    </div>
  );
}

function One({
  block,
  onAction,
  disabled,
}: {
  block: Block;
  onAction?: OnAction | undefined;
  disabled?: boolean | undefined;
}) {
  if (block.type === 'divider') return <hr className="border-line" />;
  if (block.type === 'context') {
    return (
      <div className="text-muted text-xs leading-relaxed">
        {block.elements.map((e, j) => (
          <Mrkdwn key={j} text={e.text} />
        ))}
      </div>
    );
  }
  if (block.type === 'actions') {
    return <Actions elements={block.elements} onAction={onAction} disabled={disabled} />;
  }
  return <Mrkdwn text={block.text.text} />;
}

/**
 * A message's blocks. An item's card and the block under it (its buttons, or who decided it)
 * form one group named after the person and the access, so a screen reader says which item
 * a Keep or Revoke button is for.
 */
export function Blocks({
  payload,
  items,
  onAction,
  disabled,
}: {
  payload: SlackPayload;
  items?: Record<string, Item>;
  onAction?: OnAction | undefined;
  disabled?: boolean;
}) {
  const drawn: ReactNode[] = [];
  const blocks = payload.blocks;
  let cards = 0;
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    if (!block) continue;
    const id = block.type === 'section' ? block.block_id : undefined;
    const item = id?.startsWith('i:') ? items?.[id.slice(2)] : undefined;
    if (!item) {
      drawn.push(<One key={i} block={block} onAction={onAction} disabled={disabled} />);
      continue;
    }
    const next = blocks[i + 1];
    const own = next && (next.type === 'context' || next.type === 'actions') ? next : undefined;
    drawn.push(
      <div
        key={i}
        role="group"
        data-item={item.key}
        aria-label={`${item.name || item.user}: ${item.target}`}
        className={cards++ ? 'border-line mt-4 border-t pt-4' : undefined}
      >
        <Card item={item} />
        {own && <One block={own} onAction={onAction} disabled={disabled} />}
      </div>,
    );
    if (own) i++;
  }
  return <>{drawn}</>;
}

/** A Jira ticket's description (Atlassian Document Format). Links are drawn as text. */
export function Adf({ doc }: { doc: AdfDoc }) {
  return (
    <div className="space-y-2">
      {doc.content.map((p, i) => (
        <p key={i} className="break-words">
          {(p.content ?? []).map((t, j) => {
            const mark = t.marks?.[0]?.type;
            if (mark === 'strong') {
              return (
                <strong key={j} className="text-ink font-semibold">
                  {t.text}
                </strong>
              );
            }
            if (mark === 'code') {
              return (
                <code
                  key={j}
                  className="bg-surface-2 rounded px-1 font-mono text-[0.85em] break-all"
                >
                  {t.text}
                </code>
              );
            }
            if (mark === 'link') {
              return (
                <span key={j} className="text-accent">
                  {t.text}
                </span>
              );
            }
            return <span key={j}>{t.text}</span>;
          })}
        </p>
      ))}
    </div>
  );
}
