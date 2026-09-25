// The shape of src/data/demo/<variant>.json, as the tool's scripts/export_demo.py writes it.

export const KEEP = 'keep';
export const REVOKE = 'revoke';
export const DECIDE = 'decide';
export type Decision = typeof KEEP | typeof REVOKE;
export type Proposal = Decision | typeof DECIDE;

export const HR_RECORD = 'hr_record';
export const CROSS_SOURCE = 'cross_source';
/** Items that can only be acknowledged (recorded as keep). */
export const ACKNOWLEDGE_ONLY: readonly string[] = [HR_RECORD, CROSS_SOURCE];

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

/** Atlassian Document Format, as the tool writes it. */
export interface AdfText {
  type: 'text';
  text: string;
  marks?: ({ type: 'strong' | 'code' } | { type: 'link'; attrs: { href: string } })[];
}
export interface AdfParagraph {
  type: 'paragraph';
  content?: AdfText[];
}
export interface AdfDoc {
  type: 'doc';
  version: 1;
  content: AdfParagraph[];
}

export interface JiraFields {
  project: { key: string };
  labels: string[];
  issuetype: { name: string };
  summary: string;
  duedate: string;
  description: AdfDoc;
  parent?: { key: string };
}

export interface RevokeTicket {
  /** Tickets are opened in this order over the items actually revoked. */
  order: number;
  fields: JiraFields;
  todo: string;
  due: string;
  label: string;
  /** The Why: line when the decision has no reason of its own. */
  why_if_empty: string;
}

export interface Item {
  key: string;
  kind: string;
  name: string;
  user: string;
  user_id: string;
  target: string;
  target_id: string;
  via: string;
  proposed: Proposal;
  reason: string;
  reviewer: string;
  facts: string[];
  concerns: string[];
  outside_okta: string[];
  outside_okta_gap: string;
  render: {
    chunk: number;
    /** The Slack card's text, before a decision. */
    card: string;
    leaver_ticket: string | null;
    /** The item's lines in the sign-off list, up to the decision's own line. */
    signoff: string[];
    concerns: ({ check_id: string; severity: Severity } | null)[];
    outside_okta: ({ check_id: string; severity: Severity } | null)[];
    revoke: RevokeTicket | null;
  };
}

export interface SlackPayload {
  text: string;
  blocks: Block[];
  thread_ts?: string;
  reply_broadcast?: boolean;
}

export type Block =
  | { type: 'section'; block_id?: string; text: { type: 'mrkdwn'; text: string } }
  | { type: 'context'; elements: { type: 'mrkdwn'; text: string }[] }
  | { type: 'divider' }
  | { type: 'actions'; block_id: string; elements: Button[] };

export interface Button {
  type: 'button';
  action_id: string;
  text: { type: 'plain_text'; text: string };
  value: string;
  style?: 'primary' | 'danger';
  confirm?: {
    title: { type: 'plain_text'; text: string };
    text: { type: 'mrkdwn'; text: string };
    confirm: { type: 'plain_text'; text: string };
    deny: { type: 'plain_text'; text: string };
  };
}

export type SlackCall =
  | { call: 'post' | 'update'; channel: string; ts: string; payload: SlackPayload }
  | {
      call: 'upload';
      channel: string;
      thread_ts: string;
      filename: string;
      title: string;
      comment: string;
      sha256: string;
    };

/** A message posted or updated, as opposed to a file uploaded. */
export type Message = Extract<SlackCall, { payload: SlackPayload }>;
export const isPost = (c: SlackCall): c is Message => c.call === 'post';

export type JiraCall =
  | { call: 'create'; key: string; fields: JiraFields }
  | { call: 'comment'; key: string; body: AdfDoc };

export interface FixTicket {
  check_id: string;
  due: string;
  fields: JiraFields;
  label: string;
  todo: string;
  verify: 'okta' | 'reviewer';
}

export interface Tamper {
  file: 'manifest.json' | 'review_items.json' | 'signoff/decisions.json';
  from: string;
  to: string;
  why: string;
}

export interface DemoData {
  format: 1;
  source: { repo: string; commit: string; tool: string; variant: string };
  variant: { github: boolean; failed_read: boolean };
  clock: { opened: string; decided: string };
  settings: {
    ciso: string;
    dm: string;
    channel: string;
    evidence_bucket: string;
    jira_project: string;
    review_days: number;
    revoke_days: number;
    leaver_hours: number;
    task_token: string;
    ticket_revoke_days: number;
    parent_issue: string;
    chunk: number;
    max_text: number;
    max_list_sections: number;
    record_name: string;
  };
  run: {
    name: string;
    manifest_text: string;
    manifest_sha256: string;
    items_text: string;
    items_sha256: string;
    gaps: string[];
    check_counts: [string, string, Severity, number][];
    pdf: { file: string; sha256: string; bytes: number };
  };
  items: Item[];
  open: {
    result: { items: number; run: string; urgent_tickets: number };
    slack: SlackCall[];
    jira: JiraCall[];
    records: Record<string, string>;
  };
  fix_tickets: FixTicket[];
  tampers: Tamper[];
  scenarios: string[];
}

export type Choice = [key: string, decision: string, reason: string];

export type Step =
  | { do: 'record'; choices: Choice[]; refused?: boolean }
  | { do: 'confirm'; refused?: boolean }
  | { do: 'approve'; refused?: boolean };

export interface Progress {
  total: number;
  decided: number;
  keep: number;
  revoke: number;
  open: number;
}

export interface GoldenScenario {
  steps: (Step & { result: unknown })[];
  slack: SlackCall[];
  jira: JiraCall[];
  step_functions: unknown[];
  records: {
    decisions: Record<string, string>;
    signoff: Record<string, string>;
    tickets: Record<string, string>;
  };
  decisions_text: string;
  decisions_sha256: string;
  attest: Record<string, string>;
  tampers: (Tamper & { offset: number })[];
}

export interface Golden {
  format: 1;
  source: DemoData['source'];
  scenarios: Record<string, GoldenScenario>;
}
