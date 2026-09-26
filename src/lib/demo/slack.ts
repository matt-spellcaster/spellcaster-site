// The Slack messages the review posts, ported from the tool's slack_review.py. Each card's
// own text comes ready-made in the export (render.card, render.signoff); what's built here is
// what depends on the decisions.

import { compact, len } from './py';
import {
  ACKNOWLEDGE_ONLY,
  DECIDE,
  KEEP,
  REVOKE,
  type Block,
  type Item,
  type Progress,
  type SlackPayload,
} from './types';

export const LABEL: Record<string, string> = {
  keep: 'Keep',
  revoke: 'Revoke',
  decide: 'Your call',
};
const FLAGGED = 'flagged';
const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];
const SEVERITY_EMOJI: Record<string, string> = {
  critical: ':red_circle:',
  high: ':large_orange_circle:',
  medium: ':large_yellow_circle:',
  low: ':white_circle:',
  info: ':large_blue_circle:',
};

/** One decision as the review records it (decisions.consolidate). */
export interface Final {
  decision: string;
  reason: string;
  decided_by: string;
  decided_at: string;
  record: string;
}

export interface Limits {
  max_text: number;
  max_list_sections: number;
}

export function esc(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

export function clip(text: string, max: number): string {
  if (len(text) <= max) return text;
  return Array.from(text)
    .slice(0, max - 1)
    .join('')
    .concat('…');
}

/** A ticket as the tool shows it with no Jira page to link to: just its key. */
export function ticketLink(key: string | null): string {
  return key ?? '';
}

function section(text: string, blockId?: string): Block {
  return blockId
    ? { type: 'section', block_id: blockId, text: { type: 'mrkdwn', text } }
    : { type: 'section', text: { type: 'mrkdwn', text } };
}

function context(text: string): Block {
  return { type: 'context', elements: [{ type: 'mrkdwn', text }] };
}

export function itemBlocks(
  run: string,
  item: Item,
  final: Final | undefined,
  max: number,
  open = true,
): Block[] {
  const blocks = [section(item.render.card, `i:${item.key}`)];
  const ack = ACKNOWLEDGE_ONLY.includes(item.kind);
  if (final) {
    const why = final.reason ? ` · _${esc(final.reason)}_` : '';
    const mark = final.decision === KEEP ? ':white_check_mark:' : ':no_entry:';
    const label = ack ? 'Acknowledged' : LABEL[final.decision];
    blocks.push(context(clip(`${mark} *${label}* by <@${final.decided_by}>${why}`, max)));
    // Nothing to change: acknowledging is the only choice, or it is signed off.
    if (ack || !open) return blocks;
  }
  // A decided item keeps its buttons: until sign-off the CISO can change their mind.
  const value = compact({ r: run, k: item.key, c: item.render.chunk });
  if (ack) {
    return [
      ...blocks,
      {
        type: 'actions',
        block_id: `a:${item.key}`,
        elements: [
          {
            type: 'button',
            action_id: `decide:${KEEP}`,
            style: 'primary',
            text: { type: 'plain_text', text: 'Acknowledge' },
            value,
          },
        ],
      },
    ];
  }
  const buttons = [KEEP, REVOKE].map((decision) => ({
    type: 'button' as const,
    action_id: `decide:${decision}`,
    text: { type: 'plain_text' as const, text: LABEL[decision] ?? decision },
    value,
    ...(decision === item.proposed
      ? { style: decision === REVOKE ? ('danger' as const) : ('primary' as const) }
      : {}),
  }));
  return [...blocks, { type: 'actions', block_id: `a:${item.key}`, elements: buttons }];
}

export function chunkMessage(
  run: string,
  index: number,
  count: number,
  chunk: Item[],
  final: Record<string, Final>,
  max: number,
  open = true,
): SlackPayload {
  const blocks: Block[] = [context(`Access review \`${run}\` · items ${index + 1} of ${count}`)];
  for (const item of chunk) blocks.push(...itemBlocks(run, item, final[item.key], max, open));
  return { text: `Access review items (${index + 1} of ${count})`, blocks };
}

export function summaryMessage(
  run: string,
  items: Item[],
  final: Record<string, Final>,
  due: string,
  manifestSha256: string,
  parent: string | null,
  open: boolean,
  unusedDays: number,
): SlackPayload {
  const pending = items.filter((i) => !(i.key in final));
  const confirmable = pending.filter((i) => i.proposed === KEEP || i.proposed === REVOKE);
  const by = (p: string) => items.filter((i) => i.proposed === p).length;
  const lines = [
    `:clipboard: *Okta access review \`${run}\`*: you're the reviewer for all ${items.length} items.`,
    `${by(KEEP)} proposed keep, ${by(REVOKE)} proposed revoke, ${by(DECIDE)} need your call.`,
    `Due *${due}*. ${items.length - pending.length} of ${items.length} decided.` +
      (parent ? ` Tracking ticket ${ticketLink(parent)}.` : ''),
    `Revoke is proposed for direct app access with no sign-in in ${unusedDays} days, and for people HR ` +
      'says have left. ' +
      'Keeping something proposed for revocation, or overriding a proposal, asks for a reason. ' +
      'When every item is decided, you get one message listing all of them with the *Approve review* button.',
  ];
  const blocks: Block[] = [section(lines.join('\n'))];
  if (open && confirmable.length) {
    blocks.push({
      type: 'actions',
      block_id: 'confirm',
      elements: [
        {
          type: 'button',
          action_id: 'confirm_proposed',
          style: 'primary',
          text: { type: 'plain_text', text: `Confirm ${confirmable.length} proposed` },
          value: compact({ r: run }),
          confirm: {
            title: { type: 'plain_text', text: 'Confirm proposals?' },
            text: {
              type: 'mrkdwn',
              text:
                `Accept the proposed keep/revoke for ${confirmable.length} items. ` +
                'Items that need your call stay open.',
            },
            confirm: { type: 'plain_text', text: 'Confirm' },
            deny: { type: 'plain_text', text: 'Cancel' },
          },
        },
      ],
    });
  }
  blocks.push(context(`Manifest SHA-256 \`${manifestSha256}\``));
  return { text: `Okta access review ${run}: ${pending.length} items left`, blocks };
}

/** The decision's own line under an item in the sign-off list, or none. */
export function whyLine(item: Item, final: Final): string | null {
  const why: string[] = [];
  if (item.proposed !== DECIDE && item.proposed !== final.decision) {
    why.push(`overrode proposed ${(LABEL[item.proposed] ?? '').toLowerCase()}`);
  }
  if (final.reason) why.push(`reason: _${esc(final.reason)}_`);
  else if (item.proposed === final.decision) why.push(`as proposed: ${esc(item.reason)}`);
  return why.length ? '      ' + why.join('; ') : null;
}

/** Every decision as one entry, grouped by outcome. items are in card order. */
export function decisionLines(
  items: Item[],
  final: Record<string, Final>,
): Record<string, string[]> {
  const grouped: Record<string, string[]> = { [REVOKE]: [], [KEEP]: [], [FLAGGED]: [] };
  for (const item of items) {
    const d = final[item.key];
    if (!d) continue;
    if (ACKNOWLEDGE_ONLY.includes(item.kind)) {
      grouped[FLAGGED]?.push(item.render.signoff.join('\n'));
      continue;
    }
    const why = whyLine(item, d);
    grouped[d.decision]?.push([...item.render.signoff, ...(why === null ? [] : [why])].join('\n'));
  }
  return grouped;
}

/** A titled list split into sections under Slack's size limit (lengths in code points). */
export function sections(title: string, lines: string[], max: number, bold = true): Block[] {
  const out: Block[] = [];
  let current = bold ? `*${title}*` : title;
  let size = len(current);
  for (const line of lines) {
    const n = len(line);
    if (size + 1 + n > max) {
      out.push(section(current));
      current = line;
      size = n;
    } else {
      current += '\n' + line;
      size += 1 + n;
    }
  }
  out.push(section(current));
  return out;
}

export function approveMessage(
  run: string,
  items: Item[],
  final: Record<string, Final>,
  progress: Progress,
  manifestSha256: string,
  parent: string | null,
  signed: { slack_user: string; signed_at: string } | null,
  revokeDays: number,
  limits: Limits,
): SlackPayload {
  const grouped = decisionLines(items, final);
  const revokes = grouped[REVOKE] ?? [];
  const keeps = grouped[KEEP] ?? [];
  const flaggedLines = grouped[FLAGGED] ?? [];
  const flagged = flaggedLines.length;
  const head = [
    `:white_check_mark: *Every item in access review \`${run}\` has a decision.* Please check them and sign off.`,
    `${progress.total} items: *${progress.revoke} revoke*, ${progress.keep - flagged} keep` +
      (flagged ? `, ${flagged} flagged for HR` : '') +
      '.' +
      (parent ? ` Tracking ticket ${ticketLink(parent)}.` : ''),
    `Approving opens one Jira ticket per revoke, due in ${revokeDays} days.` +
      (flagged ? ' Accounts with no HR record get no ticket: raise them with HR.' : ''),
  ];
  const blocks: Block[] = [section(head.join('\n'))];
  let listed: Block[] = [];
  if (revokes.length) {
    listed.push(...sections(`:no_entry: Revoke (${revokes.length})`, revokes, limits.max_text));
  }
  if (keeps.length) {
    listed.push(...sections(`:white_check_mark: Keep (${keeps.length})`, keeps, limits.max_text));
  }
  if (flagged) {
    listed.push(
      ...sections(
        `:triangular_flag_on_post: Flagged for HR (${flagged}), no ticket`,
        flaggedLines,
        limits.max_text,
      ),
    );
  }
  if (listed.length > limits.max_list_sections) {
    listed = [
      ...listed.slice(0, limits.max_list_sections),
      section('…the list continues in the report PDF in this thread.'),
    ];
  }
  blocks.push({ type: 'divider' }, ...listed, { type: 'divider' });
  blocks.push(
    context(`Manifest SHA-256 \`${manifestSha256}\` · the report PDF is in this message's thread.`),
  );
  if (signed) {
    blocks.push(
      context(
        `:lock: Signed off by <@${signed.slack_user}> at ${signed.signed_at}. ` +
          'Remediation tickets are being opened.',
      ),
    );
  } else {
    blocks.push({
      type: 'actions',
      block_id: 'approve',
      elements: [
        {
          type: 'button',
          action_id: 'approve',
          style: 'primary',
          text: { type: 'plain_text', text: 'Approve review' },
          value: compact({ r: run }),
          confirm: {
            title: { type: 'plain_text', text: 'Sign off this review?' },
            text: {
              type: 'mrkdwn',
              text:
                'This records your sign-off against the manifest above and opens ' +
                `${progress.revoke} remediation ticket(s). It can't be undone. ` +
                'To change a decision first, click its button again in the ' +
                'item messages above.',
            },
            confirm: { type: 'plain_text', text: 'Sign off' },
            deny: { type: 'plain_text', text: 'Cancel' },
          },
        },
      ],
    });
  }
  return { text: `Access review ${run} is ready for sign-off`, blocks };
}

export interface ChecklistEntry {
  ticket: string;
  todo: string;
  due: string | null;
  verify: 'okta' | 'reviewer';
}

export function checklistMessage(
  run: string,
  parent: string | null,
  entries: ChecklistEntry[],
  max: number,
): SlackPayload {
  // Nothing is verified yet when the checklist is first posted, so every line is open.
  const lines = [
    `:clipboard: *To close ${ticketLink(parent) || 'the tracking ticket'}* (0 of ${entries.length} done)`,
  ];
  const sorted = [...entries].sort((a, b) =>
    (a.due ?? '') !== (b.due ?? '')
      ? (a.due ?? '') < (b.due ?? '')
        ? -1
        : 1
      : a.ticket < b.ticket
        ? -1
        : a.ticket > b.ticket
          ? 1
          : 0,
  );
  for (const e of sorted) {
    const word = e.verify === 'reviewer' ? ' · taken on your word' : '';
    lines.push(
      `:white_large_square: ${ticketLink(e.ticket)} ${esc(e.todo)} — due ${e.due || '?'}${word}`,
    );
  }
  const link = ticketLink(parent);
  const how = entries.length
    ? 'How: make each change in Okta, then resolve its ticket in JSM. The daily check (07:00) ' +
      'confirms it in Okta and ticks it off here. The lines marked *taken on your word* are ' +
      'ticked off as soon as they are resolved, without Okta being consulted: they ask for a ' +
      'decision (inactive or unused accounts, contractor exceptions, API client scopes), for a ' +
      'service account to be handed over, or for a change in another source. This review reads ' +
      'each of those once and does not re-read it to confirm a fix. When every line is ticked, ' +
      `${link || 'the tracking ticket'} closes ` +
      'automatically.'
    : `Nothing to fix. ${link || 'The tracking ticket'} closes at the next daily check.`;
  return {
    text: `Access review ${run}: 0 of ${entries.length} action items done`,
    blocks: [...sections(lines[0] ?? '', lines.slice(1), max, false), context(how)],
  };
}

export interface Manifest {
  finding_counts?: Record<string, number>;
  data_gaps?: string[];
  org_url?: string;
  review_date?: string;
  config?: { app_unused_days?: unknown };
  files: Record<string, string>;
}

export function channelFinished(
  run: string,
  manifest: Manifest,
  checkCounts: [string, string, string, number][],
  attestation: { slack_user: string; signed_at: string; decision: string; manifest_sha256: string },
  keeps: number,
  revokes: number,
  parent: string | null,
  revokeDays: number,
  fixes: number,
  flagged: number,
  max: number,
): SlackPayload {
  const counts = manifest.finding_counts ?? {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const bySev =
    SEVERITY_ORDER.filter((s) => counts[s])
      .map((s) => `${counts[s]} ${s}`)
      .join(', ') || 'none';
  const gaps = manifest.data_gaps ?? [];
  const lines = [
    `:white_check_mark: *Okta access review \`${run}\` is finished.*`,
    `Signed off by <@${attestation.slack_user}> at ${attestation.signed_at} (${attestation.decision}).`,
    `*Findings:* ${total} (${bySev}).` +
      (gaps.length
        ? ` :warning: Data incomplete: ${gaps.length} gap(s), see the report.`
        : ' Data complete.'),
  ];
  const order = (s: string) => {
    const i = SEVERITY_ORDER.indexOf(s);
    return i < 0 ? 9 : i;
  };
  const sorted = [...checkCounts].sort((a, b) =>
    order(a[2]) !== order(b[2])
      ? order(a[2]) - order(b[2])
      : a[0] < b[0]
        ? -1
        : a[0] > b[0]
          ? 1
          : 0,
  );
  for (const [checkId, title, severity, n] of sorted) {
    lines.push(`${SEVERITY_EMOJI[severity] ?? '•'}  \`${checkId}\` ${esc(title)} ×${n}`);
  }
  lines.push(
    `*Decisions:* ${keeps} keep, ${revokes} revoke.` +
      (flagged
        ? ` ${flagged} account(s) with no HR record acknowledged and flagged for HR; no ticket is ` +
          'opened for those.'
        : ''),
  );
  const link = ticketLink(parent) || '-';
  if (revokes || fixes) {
    lines.push(
      `*Tickets:* ${revokes} to remove access and ${fixes} to fix findings, under ` +
        `${link}, due in ${revokeDays} days. The action list is in the ` +
        'approval thread; the tracking ticket closes once every one is settled, each ' +
        "either verified in Okta or resolved on the reviewer's word.",
    );
  } else {
    lines.push(`Nothing to fix. Tracking ticket ${link} closes at the next daily check.`);
  }
  return {
    text: `Okta access review ${run} is finished`,
    blocks: [
      section(clip(lines.join('\n'), max)),
      context(
        `Manifest SHA-256 \`${attestation.manifest_sha256}\` · :lock: Names and details are only in the ` +
          'report and JSM.',
      ),
    ],
  };
}

const KIND: Record<string, string> = {
  app: 'App',
  admin_role: 'Admin role',
  admin_group: 'Admin group',
  hr_record: 'HR record',
  cross_source: 'Outside this decision',
};

/** The "Reason needed" modal's text (slack_review.reason_modal). */
export function reasonModalText(item: Item, decision: string, max: number): string {
  return clip(
    `*${LABEL[decision]}* ${(KIND[item.kind] ?? item.kind).toLowerCase()} *${esc(item.target)}* for ` +
      `*${esc(item.user)}*.\nProposed was *${LABEL[item.proposed]}*: ${esc(item.reason)}`,
    max,
  );
}
