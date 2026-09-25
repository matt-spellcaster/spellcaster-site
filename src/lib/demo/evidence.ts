// The evidence check: what the tool's `access-review attest reports/<run>` prints for the
// signed review, intact or with one byte changed. Ported from attest.py and
// decisions.signoff_problems.
//
// The page has the bytes of the three files a reviewer would want to change (the manifest,
// the review items and the signed decisions) and re-hashes those. The run's other files
// (the report, the snapshot, the findings) aren't on the page, so they count as matching.

import { sha256Hex } from './sha';
import type { Attestation } from './review';
import type { Tamper } from './types';

export const ITEMS_FILE = 'review_items.json';

export interface Files {
  'manifest.json': string;
  'review_items.json': string;
  'signoff/decisions.json': string;
}

export type Located = Tamper & { offset: number };

const encode = (text: string) => new TextEncoder().encode(text);

function indexOf(body: Uint8Array, find: Uint8Array): number {
  outer: for (let i = 0; i + find.length <= body.length; i++) {
    for (let j = 0; j < find.length; j++) if (body[i + j] !== find[j]) continue outer;
    return i;
  }
  return -1;
}

/** The export's three one-byte changes (scripts/export_demo.py tampers()), for these files. */
export function locate(files: Files): Located[] {
  const manifest = JSON.parse(files['manifest.json']) as { finding_counts: { critical: number } };
  const critical = manifest.finding_counts.critical;
  const decided = /"decided_at": "\d{4}-\d\d-(\d\d)/.exec(files['signoff/decisions.json']);
  if (!decided) throw new Error('signoff/decisions.json has no decided_at');
  const day = Number(decided[1]);
  const wanted: [Tamper['file'], string, string, string][] = [
    [
      'manifest.json',
      `"critical": ${critical},`,
      `"critical": ${critical - 1},`,
      'hide one critical finding',
    ],
    [
      ITEMS_FILE,
      '"app_unused_days": 90,',
      '"app_unused_days": 30,',
      'change the rule the proposals followed',
    ],
    [
      'signoff/decisions.json',
      decided[0],
      decided[0].slice(0, -2) + String(day - 1).padStart(2, '0'),
      'backdate a decision by a day',
    ],
  ];
  return wanted.map(([file, find, replace, why]) => {
    const body = encode(files[file]);
    const a = encode(find);
    const b = encode(replace);
    const at = indexOf(body, a);
    const diff = Array.from(a.keys()).filter((n) => a[n] !== b[n]);
    if (at < 0 || a.length !== b.length || diff.length !== 1) {
      throw new Error(`can't make a one-byte change to ${file}`);
    }
    const n = diff[0] ?? 0;
    return {
      file,
      offset: at + n,
      from: String.fromCharCode(body[at + n] ?? 0),
      to: String.fromCharCode(b[n] ?? 0),
      why,
    };
  });
}

/** The files with one byte changed. */
export function apply(files: Files, change: Located): Files {
  const body = encode(files[change.file]);
  if (String.fromCharCode(body[change.offset] ?? 0) !== change.from) {
    throw new Error(`${change.file} isn't the file the change was made for`);
  }
  body[change.offset] = change.to.charCodeAt(0);
  return { ...files, [change.file]: new TextDecoder().decode(body) };
}

export interface Checked {
  /** What attest prints, ending with the exit code, as the export records it. */
  output: string;
  code: 0 | 2;
  manifestSha256: string;
  itemsSha256: string;
  decisionsSha256: string;
}

export async function attest(
  run: string,
  files: Files,
  attestation: Attestation,
): Promise<Checked> {
  const manifestSha256 = await sha256Hex(files['manifest.json']);
  const itemsSha256 = await sha256Hex(files[ITEMS_FILE]);
  const decisionsSha256 = await sha256Hex(files['signoff/decisions.json']);
  const manifest = JSON.parse(files['manifest.json']) as { files: Record<string, string> };
  const names = Object.keys(manifest.files).sort();
  const changed = names.filter((n) => n === ITEMS_FILE && manifest.files[n] !== itemsSha256);
  const lines = [
    `reports/${run}: ${names.length - changed.length} of ${names.length} files match manifest.json ` +
      `(SHA-256 ${manifestSha256})`,
    ...changed.map((n) => `  CHANGED   ${n}`),
  ];

  const problems: string[] = [];
  if (attestation.manifest_sha256 !== manifestSha256) {
    problems.push('the sign-off was made against a different manifest.json');
  }
  if (attestation.decisions_sha256 !== decisionsSha256) {
    problems.push('signoff/decisions.json has changed since the sign-off');
  }
  const doc = JSON.parse(files['signoff/decisions.json']) as {
    manifest_sha256?: string;
    decisions?: Record<string, unknown>;
  };
  if (doc.manifest_sha256 !== manifestSha256) {
    problems.push('signoff/decisions.json belongs to a different manifest.json');
  }
  const items = (JSON.parse(files[ITEMS_FILE]) as { items: { key: string }[] }).items.map(
    (i) => i.key,
  );
  const decided = Object.keys(doc.decisions ?? {});
  if (decided.length !== items.length || !items.every((k) => decided.includes(k))) {
    problems.push("signoff/decisions.json doesn't cover exactly the review's items");
  }
  if (!problems.length) {
    const a = attestation;
    lines.push(
      `Slack sign-off: ${a.signed_at}  ${a.decision}  ${a.reviewer}  ` +
        `(${a.items_decided} items, ${a.items_revoked} revoked)`,
    );
  }
  lines.push(...problems.map((p) => `  PROBLEM   ${p}`));
  const code = changed.length || problems.length ? 2 : 0;
  if (code) lines.push("access-review: this review doesn't match its evidence.");
  return {
    output: `${lines.join('\n')}\nexit ${code}\n`,
    code,
    manifestSha256,
    itemsSha256,
    decisionsSha256,
  };
}
