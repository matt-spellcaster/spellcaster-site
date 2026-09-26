// What the golden replays can't reach: input a visitor types that the tool's scripted
// scenarios never used, the refusals the scenarios didn't hit, and the demo's own copy
// against the data it describes.

import { readFileSync } from 'node:fs';
import { isValidElement } from 'react';
import { describe, expect, it } from 'vitest';
import { copy } from '../../src/components/demo/copy';
import { inline } from '../../src/components/demo/Mrkdwn';
import {
  approve,
  confirm,
  DecisionError,
  openReview,
  record,
  type Review,
} from '../../src/lib/demo/review';
import { sections } from '../../src/lib/demo/slack';
import { KEEP, REVOKE, type DemoData } from '../../src/lib/demo/types';

const data = JSON.parse(readFileSync('src/data/demo/web.json', 'utf8')) as DemoData;

describe('a reason the visitor types', () => {
  it('goes into the revoke ticket as written, $ patterns and all', async () => {
    const item = data.items.find((i) => i.proposed === KEEP && i.render.revoke);
    if (!item) throw new Error('the data has no keep proposal with a revoke ticket');
    const reason = "costs $& and $' and $` and $$ a seat";
    let review = record(openReview(data), [[item.key, REVOKE, reason]]).review;
    review = confirm(review).review;
    for (const i of review.items.filter((i) => !(i.key in review.final))) {
      review = record(review, [[i.key, i.proposed === 'decide' ? KEEP : i.proposed, 'ok']]).review;
    }
    review = (await approve(review)).review;
    const tickets = JSON.stringify(review.jira.filter((c) => c.call === 'create'));
    expect(tickets).toContain(JSON.stringify(reason).slice(1, -1));
    expect(tickets).not.toContain('\ue000'); // the slot, as JSON.stringify writes it
  });

  it('is bold or italic only at a word boundary, as in Slack', () => {
    const tags = (text: string) =>
      inline(text).map((n) => (isValidElement(n) ? String(n.type) : 'text'));
    expect(tags('*a* and _b_')).toStrictEqual(['strong', 'text', 'em']);
    expect(tags('config.service_accounts_x_')).toStrictEqual(['text']);
    expect(tags('a*b* 𝐀*c* é_d_')).toStrictEqual(['text']);
    expect(tags('(*a*) 😀_b_')).toStrictEqual(['text', 'strong', 'text', 'em']);
  });

  it('is drawn as text when it names an emoji Slack has no picture for', () => {
    for (const name of ['__proto__', 'constructor', 'toString']) {
      const out = inline(`see :${name}: here`);
      expect(out.filter(isValidElement), name).toStrictEqual([]);
      expect(out.join(''), name).toBe(`see :${name}: here`);
    }
  });
});

describe('the refusals the scenarios never hit', () => {
  const open = (): Review => openReview(data);

  it('refuses what the tool refuses, and changes nothing', async () => {
    const review = open();
    expect(() => record(review, [])).toThrow('nothing to record');
    expect(() => record(review, [['no-such-key', KEEP, '']])).toThrow(
      "that item isn't part of this review",
    );
    const first = data.items[0];
    if (!first) throw new Error('no items');
    expect(() => record(review, [[first.key, 'maybe', '']])).toThrow(DecisionError);
    await expect(approve(review)).rejects.toThrow(/item\(s\) still need a decision/);
    expect(review.records).toStrictEqual({});
    expect(review.jira).toStrictEqual([]);
  });

  it('refuses a second confirm, and anything after sign-off', async () => {
    let review = confirm(open()).review;
    expect(() => confirm(review)).toThrow('there are no undecided proposals to confirm');
    for (const i of review.items.filter((i) => !(i.key in review.final))) {
      review = record(review, [[i.key, KEEP, 'ok']]).review;
    }
    const signed = (await approve(review)).review;
    expect(() => record(signed, [[review.items[0]?.key ?? '', KEEP, '']])).toThrow(
      'this review has already been signed off',
    );
    await expect(approve(signed)).rejects.toThrow('this review has already been signed off');
  });
});

describe('a sign-off entry too long for a section', () => {
  // The demo's form caps reasons, so no scenario reaches this; the tool clips such a line.
  it('is clipped to the limit in code points, and the lines around it are kept', () => {
    const max = data.settings.max_text;
    const long = '• ' + '😀'.repeat(max);
    const texts = sections('Keep (3)', ['• first', long, '• last'], max).map(
      (b) => (b as { text: { text: string } }).text.text,
    );
    expect(texts.map((t) => Array.from(t).length).every((n) => n <= max)).toBe(true);
    expect(texts).toEqual([
      '*Keep (3)*\n• first',
      Array.from(long)
        .slice(0, max - 1)
        .join('') + '…',
      '• last',
    ]);
  });

  it('keeps a line of exactly the limit and clips one over it', () => {
    const max = data.settings.max_text;
    const exact = '😀'.repeat(max);
    const texts = (lines: string[]) =>
      sections('T', lines, max).map((b) => (b as { text: { text: string } }).text.text);
    expect(texts([exact])).toEqual(['*T*', exact]);
    expect(texts([exact + '😀'])).toEqual(['*T*', '😀'.repeat(max - 1) + '…']);
  });

  it('clips a heading too long for a section, bold or not', () => {
    const max = data.settings.max_text;
    const title = '😀'.repeat(max + 1);
    for (const bold of [true, false]) {
      const texts = sections(title, ['• a'], max, bold).map(
        (b) => (b as { text: { text: string } }).text.text,
      );
      const heading = bold ? `*${title}*` : title;
      expect(texts).toEqual([
        Array.from(heading)
          .slice(0, max - 1)
          .join('') + '…',
        '• a',
      ]);
    }
  });
});

describe("the demo's copy", () => {
  const strings = (v: unknown): string[] =>
    typeof v === 'string'
      ? [v]
      : typeof v === 'function'
        ? [String((v as (...a: string[]) => unknown)('1234567', '2'))]
        : Object.values(v ?? {}).flatMap(strings);

  it('has no [placeholders] left (CLAUDE.md rule 6; most of it is only in the JavaScript)', () => {
    expect(strings(copy).filter((s) => /\[[^\]\n]{1,80}\]/.test(s))).toStrictEqual([]);
  });

  it('counts what the data holds', () => {
    const manifest = JSON.parse(data.run.manifest_text) as { files: Record<string, string> };
    // "The run's other six files": the manifest's, less review_items.json, which is on the page.
    expect(copy.steps.evidence.scope).toContain('other six files');
    expect(Object.keys(manifest.files).length - 1).toBe(6);
    // "One person HR says has left ... their ticket is already open": the opening tickets,
    // less the parent.
    expect(copy.steps.open.body).toContain('One person HR says has left');
    expect(data.open.jira.filter((c) => c.call === 'create').length - 1).toBe(1);
  });
});
