// One review, from the moment it opens to the tickets after sign-off, ported from the tool's
// workflow.py, decisions.py and tickets.py. Every function returns a new state and leaves the
// old one alone, so the page can keep it in React state. A refused action throws
// DecisionError with the tool's own message, and changes nothing.

import { checkText, dumps, strip } from './py';
import { sha256Hex } from './sha';
import {
  approveMessage,
  channelFinished,
  checklistMessage,
  chunkMessage,
  summaryMessage,
  type ChecklistEntry,
  type Final,
  type Manifest,
} from './slack';
import {
  ACKNOWLEDGE_ONLY,
  DECIDE,
  HR_RECORD,
  KEEP,
  REVOKE,
  type AdfDoc,
  type AdfParagraph,
  type AdfText,
  type Choice,
  type DemoData,
  type Item,
  type JiraCall,
  type JiraFields,
  type Progress,
  type SlackCall,
  type SlackPayload,
  isPost,
} from './types';

export const MAX_NOTE = 1000;
const FORMAT = 1;
const DECISIONS: readonly string[] = [KEEP, REVOKE];
/** Where the tool writes the reason while it builds a revoke ticket (U+E000, private use). */
const SLOT = '\ue000';

export class DecisionError extends Error {}

export interface DecisionRecord {
  channel: string;
  decisions: { decision: string; item_key: string; reason: string }[];
  format: number;
  manifest_sha256: string;
  message_ts: string;
  recorded_at: string;
  run: string;
  slack_team: string;
  slack_user: string;
}

export interface Attestation {
  channel: string;
  decision: 'approved' | 'approved-with-exceptions';
  decisions_sha256: string;
  extra_files: string[];
  files_verified: number;
  items_decided: number;
  items_revoked: number;
  manifest_sha256: string;
  message_ts: string;
  note: string;
  org_url: string | null;
  prev: null;
  review_date: string | null;
  reviewer: string;
  signed_at: string;
  slack_team: string;
  slack_user: string;
  tool: string;
}

/** What approve() hands Step Functions: IDs, hashes and counts. */
export interface Signed extends Progress {
  run: string;
  manifest_sha256: string;
  decisions_sha256: string;
}

export interface Remediated {
  run: string;
  revoke_tickets: number;
  opened_now: number;
  fix_tickets: number;
}

export interface Review {
  data: DemoData;
  manifest: Manifest;
  items: Item[];
  byKey: Record<string, Item>;
  status: 'open' | 'signed-off';
  /** Decision records by file name, as written (create-only, never edited). */
  records: Record<string, string>;
  final: Record<string, Final>;
  /** Evidence records under tickets/ and signoff/, by file name. */
  tickets: Record<string, string>;
  signoff: Record<string, string>;
  attestation: Attestation | null;
  decisionsText: string | null;
  signed: Signed | null;
  remediated: Remediated | null;
  /** Every Slack and Jira call since the review opened, in order. */
  slack: SlackCall[];
  jira: JiraCall[];
  stepFunctions: Signed[];
  /** What the reviewer's DM and the channel show now, by message ts. */
  messages: Record<string, SlackPayload>;
  summaryTs: string;
  chunkTs: string[];
  channelTs: string;
  approveTs: string | null;
  checklistTs: string | null;
  finishedTs: string | null;
  nextRecord: number;
  nextTs: number;
  nextIssue: number;
}

// --- small pieces -------------------------------------------------------------------------

function stamp(iso: string): string {
  // decisions._stamp: microseconds, always zero on the demo's clock.
  return iso.replace(/Z$/, '.000000Z');
}

function recordName(data: DemoData, n: number): string {
  const [head, tail] = data.settings.record_name.split('{n:012x}');
  return `${head}${n.toString(16).padStart(12, '0')}${tail}`;
}

function ts(n: number): string {
  return `1758000000.${n.toString().padStart(6, '0')}`;
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function unusedDays(manifest: Manifest): number {
  const days = manifest.config?.app_unused_days;
  return typeof days === 'number' && Number.isInteger(days) ? days : 90;
}

export function reasonRequired(item: Item, decision: string): boolean {
  return item.proposed !== DECIDE && decision !== item.proposed;
}

export function progress(review: Pick<Review, 'items' | 'final'>): Progress {
  const decided = review.items.filter((i) => i.key in review.final);
  const count = (d: string) => decided.filter((i) => review.final[i.key]?.decision === d).length;
  return {
    total: review.items.length,
    decided: decided.length,
    keep: count(KEEP),
    revoke: count(REVOKE),
    open: review.items.length - decided.length,
  };
}

/** Items with no decision yet, in key order (decisions.outstanding). */
export function outstanding(review: Pick<Review, 'items' | 'final'>): Item[] {
  return review.items.filter((i) => !(i.key in review.final)).sort(byKey);
}

function byKey(a: Item, b: Item): number {
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

function adf(...paragraphs: (string | [string, 'strong' | 'code' | null][])[]): AdfDoc {
  const content: AdfParagraph[] = paragraphs.map((p) => {
    const pieces = typeof p === 'string' ? ([[p, null]] as const) : p;
    const nodes: AdfText[] = pieces
      .filter(([text]) => text)
      .map(([text, mark]) =>
        mark ? { type: 'text', text, marks: [{ type: mark }] } : { type: 'text', text },
      );
    return nodes.length ? { type: 'paragraph', content: nodes } : { type: 'paragraph' };
  });
  return { type: 'doc', version: 1, content };
}

/** Deep copy of a JSON value with SLOT replaced in every string. */
function fill<T>(value: T, reason: string): T {
  return JSON.parse(JSON.stringify(value), (_, v: unknown) =>
    // A function, so a $ in the reason is never read as a replacement pattern.
    typeof v === 'string' ? v.replaceAll(SLOT, () => reason) : v,
  ) as T;
}

// --- messages -----------------------------------------------------------------------------

function chunks(review: Review): Item[][] {
  const out: Item[][] = [];
  for (const item of review.items) (out[item.render.chunk] ??= []).push(item);
  return out;
}

function summary(review: Review, open: boolean): SlackPayload {
  const { data } = review;
  return summaryMessage(
    data.run.name,
    review.items,
    review.final,
    addDays(data.clock.opened, data.settings.review_days),
    data.run.manifest_sha256,
    data.settings.parent_issue,
    open,
    unusedDays(review.manifest),
  );
}

function approval(review: Review, signed: Attestation | null): SlackPayload {
  const { data } = review;
  return approveMessage(
    data.run.name,
    review.items,
    review.final,
    progress(review),
    data.run.manifest_sha256,
    data.settings.parent_issue,
    signed,
    data.settings.revoke_days,
    data.settings,
  );
}

function post(review: Review, channel: string, payload: SlackPayload): string {
  const at = ts(review.nextTs++);
  review.slack.push({ call: 'post', channel, ts: at, payload });
  review.messages[at] = payload;
  return at;
}

function update(review: Review, channel: string, at: string, payload: SlackPayload): void {
  review.slack.push({ call: 'update', channel, ts: at, payload });
  review.messages[at] = payload;
}

/** workflow.refresh: the summary and every item message. */
function refresh(review: Review): void {
  const { data } = review;
  const dm = data.settings.dm;
  update(review, dm, review.summaryTs, summary(review, review.status === 'open'));
  const parts = chunks(review);
  parts.forEach((part, n) => {
    const at = review.chunkTs[n];
    if (at) {
      update(
        review,
        dm,
        at,
        chunkMessage(data.run.name, n, parts.length, part, review.final, data.settings.max_text),
      );
    }
  });
}

/** workflow.maybe_ready, then redraw_approve: post the Approve message once, redraw it after. */
function ready(review: Review): void {
  if (outstanding(review).length) return;
  const { data } = review;
  const dm = data.settings.dm;
  if (review.approveTs === null) {
    review.approveTs = post(review, dm, approval(review, null));
    review.slack.push({
      call: 'upload',
      channel: dm,
      thread_ts: review.approveTs,
      filename: `okta-access-review-${data.run.name}.pdf`,
      title: `Okta access review (${data.run.name})`,
      comment: ':page_facing_up: The full report. :lock: Contains personal data.',
      sha256: data.run.pdf.sha256,
    });
  } else {
    update(review, dm, review.approveTs, approval(review, null));
  }
}

// --- the review ---------------------------------------------------------------------------

/** The review as it stands once open_review has run: the DM, the channel post, the tickets. */
export function openReview(data: DemoData): Review {
  const posts = data.open.slack.filter(isPost);
  const dm = posts.filter((c) => c.channel === data.settings.dm);
  const channel = posts.find((c) => c.channel === data.settings.channel);
  if (!dm[0] || !channel) throw new Error('the export has no opening messages');
  const messages: Record<string, SlackPayload> = {};
  for (const c of posts) messages[c.ts] = c.payload;
  const opened = data.open.jira.filter((c) => c.call === 'create').length;
  return {
    data,
    manifest: JSON.parse(data.run.manifest_text) as Manifest,
    items: data.items,
    byKey: Object.fromEntries(data.items.map((i) => [i.key, i])),
    status: 'open',
    records: {},
    final: {},
    tickets: { ...data.open.records },
    signoff: {},
    attestation: null,
    decisionsText: null,
    signed: null,
    remediated: null,
    slack: [],
    jira: [],
    stepFunctions: [],
    messages,
    summaryTs: dm[0].ts,
    chunkTs: dm.slice(1).map((c) => c.ts),
    channelTs: channel.ts,
    approveTs: null,
    checklistTs: null,
    finishedTs: null,
    nextRecord: 1,
    nextTs: posts.length + 1,
    nextIssue: opened + 1,
  };
}

function copy(review: Review): Review {
  return {
    ...review,
    records: { ...review.records },
    final: { ...review.final },
    tickets: { ...review.tickets },
    signoff: { ...review.signoff },
    slack: [...review.slack],
    jira: [...review.jira],
    stepFunctions: [...review.stepFunctions],
    messages: { ...review.messages },
    chunkTs: [...review.chunkTs],
  };
}

function checkOpen(review: Review): void {
  if (review.status !== 'open') throw new DecisionError('this review has already been signed off');
}

/** decisions.make_decision_record: check one action's choices and build its record. */
function makeRecord(review: Review, choices: Choice[]): DecisionRecord {
  if (!choices.length) throw new DecisionError('nothing to record');
  const entries = choices.map(([key, decision, reason]) => {
    const item = review.byKey[key];
    if (!item) throw new DecisionError("that item isn't part of this review");
    if (!DECISIONS.includes(decision)) {
      throw new DecisionError(`decision must be one of ${DECISIONS.join(', ')}`);
    }
    if (ACKNOWLEDGE_ONLY.includes(item.kind) && decision !== KEEP) {
      throw new DecisionError(
        `a ${item.kind.replaceAll('_', ' ')} item can only be acknowledged; ` +
          'the work it points at happens outside this review',
      );
    }
    const required = reasonRequired(item, decision);
    let text: string;
    try {
      text = checkText(reason, 'reason', MAX_NOTE, required);
    } catch {
      throw new DecisionError(
        required && !strip(reason)
          ? 'a reason is needed to keep access that was proposed for revocation, or to override a proposal'
          : `the reason must be one line of at most ${MAX_NOTE} characters`,
      );
    }
    return { item_key: key, decision, reason: text };
  });
  const { data } = review;
  return {
    format: FORMAT,
    run: data.run.name,
    manifest_sha256: data.run.manifest_sha256,
    decisions: entries,
    slack_user: data.settings.ciso,
    slack_team: '',
    channel: data.settings.dm,
    message_ts: '',
    recorded_at: stamp(data.clock.decided),
  };
}

/** workflow.record: store one reviewer action, then bring the messages up to date. */
export function record(review: Review, choices: Choice[]): { review: Review; result: Progress } {
  checkOpen(review);
  const rec = makeRecord(review, choices);
  const next = copy(review);
  const name = recordName(next.data, next.nextRecord++);
  next.records[name] = dumps(rec) + '\n';
  // decisions.consolidate: the latest record wins. Records are named in the order they were
  // written and all carry the same time, so applying this one last is the same thing.
  for (const entry of rec.decisions) {
    next.final[entry.item_key] = {
      decision: entry.decision,
      reason: entry.reason,
      decided_by: rec.slack_user,
      decided_at: rec.recorded_at,
      record: name,
    };
  }
  refresh(next);
  ready(next);
  return { review: next, result: progress(next) };
}

/** Every keep/revoke proposal with no decision yet (decisions.confirm_proposed). */
export function confirmable(review: Review): Choice[] {
  return review.items
    .filter((i) => DECISIONS.includes(i.proposed) && !(i.key in review.final))
    .sort(byKey)
    .map((i): Choice => [i.key, i.proposed, '']);
}

/** The "Confirm N proposed" button. */
export function confirm(review: Review): { review: Review; result: Progress } {
  const choices = confirmable(review);
  if (!choices.length) throw new DecisionError('there are no undecided proposals to confirm');
  return record(review, choices);
}

/** The CISO's sign-off (workflow.approve), then remediation (workflow.remediate). */
export async function approve(
  review: Review,
): Promise<{ review: Review; result: { approve: Signed; remediate: Remediated } }> {
  checkOpen(review);
  const missing = outstanding(review);
  if (missing.length) throw new DecisionError(`${missing.length} item(s) still need a decision`);
  const next = copy(review);
  const { data } = next;
  const run = data.run.name;
  const decisions: Record<string, Final> = {};
  for (const key of Object.keys(next.byKey).sort()) decisions[key] = next.final[key] as Final;
  const decisionsText =
    dumps({ format: FORMAT, run, manifest_sha256: data.run.manifest_sha256, decisions }) + '\n';
  const decisionsSha256 = await sha256Hex(decisionsText);
  const counts = progress(next);
  const attestation: Attestation = {
    reviewer: `slack:${data.settings.ciso}`,
    decision: counts.revoke ? 'approved-with-exceptions' : 'approved',
    note: '',
    signed_at: data.clock.decided,
    org_url: next.manifest.org_url ?? null,
    review_date: next.manifest.review_date ?? null,
    manifest_sha256: data.run.manifest_sha256,
    files_verified: Object.keys(next.manifest.files).length,
    extra_files: [],
    tool: data.source.tool,
    prev: null,
    decisions_sha256: decisionsSha256,
    items_decided: next.items.length,
    items_revoked: counts.revoke,
    slack_user: data.settings.ciso,
    slack_team: '',
    channel: data.settings.dm,
    message_ts: '',
  };
  next.decisionsText = decisionsText;
  next.attestation = attestation;
  next.signoff['decisions.json'] = decisionsText;
  next.signoff['attestation.json'] = dumps(attestation) + '\n';
  const signed: Signed = {
    run,
    manifest_sha256: data.run.manifest_sha256,
    decisions_sha256: decisionsSha256,
    ...counts,
  };
  next.signed = signed;
  next.status = 'signed-off';
  next.stepFunctions.push(signed);
  if (next.approveTs) update(next, data.settings.dm, next.approveTs, approval(next, attestation));
  refresh(next);
  const remediated = remediate(next, attestation);
  next.remediated = remediated;
  return { review: next, result: { approve: signed, remediate: remediated } };
}

/** tickets.Remediation._create: open the ticket and keep its evidence record. */
function create(
  review: Review,
  fields: JiraFields,
  rec: Record<string, unknown>,
  label: string,
): string {
  const key = `${review.data.settings.jira_project}-${review.nextIssue++}`;
  review.jira.push({ call: 'create', key, fields });
  review.tickets[`${label}.json`] =
    dumps({ ...rec, issue: key, label, created_at: review.data.clock.decided }) + '\n';
  return key;
}

function remediate(review: Review, att: Attestation): Remediated {
  const { data } = review;
  const run = data.run.name;
  const parent = data.settings.parent_issue;
  const final = review.final;
  // One ticket per revoke, in the order the export ranked them.
  const revoked = review.items
    .filter((i) => i.render.revoke && final[i.key]?.decision === REVOKE)
    .sort((a, b) => (a.render.revoke?.order ?? 0) - (b.render.revoke?.order ?? 0));
  for (const item of revoked) {
    const t = item.render.revoke;
    if (!t) continue;
    const reason = final[item.key]?.reason || t.why_if_empty;
    create(
      review,
      fill(t.fields, reason),
      { kind: 'revoke', run, item_key: item.key, due: t.due, todo: t.todo },
      t.label,
    );
  }
  for (const t of data.fix_tickets) {
    // The subject, as the summary names it: "Fix: <title> — <subject>".
    const title = t.todo.split(` (${t.check_id}) for `)[0] ?? '';
    const subject = t.fields.summary.slice(`Fix: ${title} — `.length);
    create(
      review,
      structuredClone(t.fields),
      {
        kind: 'finding',
        run,
        check_id: t.check_id,
        subject,
        due: t.due,
        todo: t.todo,
        verify: t.verify,
      },
      t.label,
    );
  }
  const revokes = revoked.length;
  review.jira.push({
    call: 'comment',
    key: parent,
    body: adf(
      `Signed off in Slack on ${att.signed_at} (${att.decision}): ${att.items_decided} items decided, ` +
        `${revokes} to revoke. ${revokes} remediation ticket(s) are linked to this one.`,
      [
        ['Manifest SHA-256: ', null],
        [att.manifest_sha256, 'code'],
      ],
      [
        ['Decisions SHA-256: ', null],
        [att.decisions_sha256, 'code'],
      ],
    ),
  });

  // workflow.post_checklist: in the approval thread, and on the tracking ticket.
  const entries = checklist(review);
  const dm = data.settings.dm;
  const message = checklistMessage(run, parent, entries, data.settings.max_text);
  if (review.approveTs) {
    review.checklistTs = post(review, dm, { ...message, thread_ts: review.approveTs });
  }
  review.jira.push({
    call: 'comment',
    key: parent,
    body: adf(
      'To close this ticket, each of these must be done and its own ticket resolved:',
      ...entries.map((e): [string, 'strong' | null][] => [
        [`${e.ticket}: `, 'strong'],
        [
          `${e.todo} (due ${e.due})` +
            (e.verify === 'reviewer' ? ' -- taken on your word, not re-read in Okta' : ''),
          null,
        ],
      ]),
      'Resolve each sub-ticket once its change is made. The daily check re-reads Okta and ticks off ' +
        'what it can see there; the lines marked above ask for a decision, or concern a source this ' +
        'review cannot re-read, so resolving them is the answer. This ticket closes automatically once ' +
        'every line is settled.',
    ),
  });

  const flagged = review.items.filter((i) => i.key in final && i.kind === HR_RECORD).length;
  const fixes = data.fix_tickets.length;
  const finished = channelFinished(
    run,
    review.manifest,
    data.run.check_counts,
    att,
    Object.keys(final).length - revokes - flagged,
    revokes,
    parent,
    data.settings.ticket_revoke_days,
    fixes,
    flagged,
    data.settings.max_text,
  );
  review.finishedTs = post(review, data.settings.channel, {
    ...finished,
    thread_ts: review.channelTs,
    reply_broadcast: true,
  });
  return { run, revoke_tickets: revokes, opened_now: revokes + fixes, fix_tickets: fixes };
}

/** Every ticket that has to be done before the tracking ticket closes, in record order. */
export function checklist(review: Review): ChecklistEntry[] {
  return Object.keys(review.tickets)
    .sort()
    .map((name) => JSON.parse(review.tickets[name] ?? '{}') as Record<string, string>)
    .filter(
      (rec) => rec['kind'] === 'leaver' || rec['kind'] === 'revoke' || rec['kind'] === 'finding',
    )
    .map((rec) => ({
      ticket: rec['issue'] ?? '',
      todo: rec['todo'] || rec['kind'] || 'ticket',
      due: rec['due'] ?? null,
      verify:
        rec['kind'] === 'finding' ? (rec['verify'] === 'reviewer' ? 'reviewer' : 'okta') : 'okta',
    }));
}

/** The reason the demo asks for: one line, at most this many characters. */
export const DEMO_REASON_MAX = 160;
