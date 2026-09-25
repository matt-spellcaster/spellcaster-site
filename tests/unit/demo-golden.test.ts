// The demo's engine against the tool itself. The tool's export ran each scripted review
// (A to E) through its real workflow code and recorded every Slack call, Jira call and
// evidence record (tests/fixtures/demo/). Replaying the same steps here has to write the
// same thing, byte for byte. Nothing is approximated: a mismatch is a bug in the port.

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { apply, attest, locate, type Files } from '../../src/lib/demo/evidence';
import {
  approve,
  confirm,
  DecisionError,
  openReview,
  record,
  type Review,
} from '../../src/lib/demo/review';
import { sha256Hex } from '../../src/lib/demo/sha';
import { chunkMessage, summaryMessage } from '../../src/lib/demo/slack';
import { isPost, type DemoData, type Golden, type Step } from '../../src/lib/demo/types';

const VARIANTS = ['okta'];

const load = <T>(path: string): T => JSON.parse(readFileSync(path, 'utf8')) as T;

async function play(review: Review, step: Step): Promise<{ review: Review; result: unknown }> {
  try {
    if (step.do === 'confirm') return confirm(review);
    if (step.do === 'record') return record(review, step.choices);
    return await approve(review);
  } catch (e) {
    if (e instanceof DecisionError) return { review, result: { error: e.message } };
    throw e;
  }
}

function files(review: Review): Files {
  return {
    'manifest.json': review.data.run.manifest_text,
    'review_items.json': review.data.run.items_text,
    'signoff/decisions.json': review.decisionsText ?? '',
  };
}

for (const variant of VARIANTS) {
  const data = load<DemoData>(`src/data/demo/${variant}.json`);
  const golden = load<Golden>(`tests/fixtures/demo/${variant}.golden.json`);

  describe(`demo data: ${variant}`, () => {
    it('comes from the same commit of the tool as the golden replays', () => {
      expect(golden.source).toStrictEqual(data.source);
      expect(Object.keys(golden.scenarios).sort()).toStrictEqual(data.scenarios);
    });

    it('hashes to what the manifest and the run say', async () => {
      expect(await sha256Hex(data.run.manifest_text)).toBe(data.run.manifest_sha256);
      expect(await sha256Hex(data.run.items_text)).toBe(data.run.items_sha256);
      const manifest = JSON.parse(data.run.manifest_text) as { files: Record<string, string> };
      expect(manifest.files['review_items.json']).toBe(data.run.items_sha256);
    });

    it('rebuilds the messages the review opened with', () => {
      const review = openReview(data);
      const [summary, ...parts] = data.open.slack
        .filter(isPost)
        .filter((c) => c.channel === data.settings.dm);
      expect(
        summaryMessage(
          data.run.name,
          data.items,
          {},
          '2026-09-22',
          data.run.manifest_sha256,
          data.settings.parent_issue,
          true,
          90,
        ),
      ).toStrictEqual(summary?.payload);
      parts.forEach((part, n) => {
        const chunk = data.items.filter((i) => i.render.chunk === n);
        expect(
          chunkMessage(data.run.name, n, parts.length, chunk, {}, data.settings.max_text),
        ).toStrictEqual(part.payload);
      });
      expect(review.nextIssue).toBe(4);
    });

    for (const [name, g] of Object.entries(golden.scenarios)) {
      describe(`scenario ${name}`, async () => {
        let review = openReview(data);
        const results: unknown[] = [];
        for (const step of g.steps) {
          const played = await play(review, step);
          review = played.review;
          results.push(played.result);
        }

        it('gives each step the same result, refusals included', () => {
          expect(results).toStrictEqual(g.steps.map((s) => s.result));
        });

        it('makes the same Slack calls, in order', () => {
          expect(review.slack.length).toBe(g.slack.length);
          review.slack.forEach((call, n) => expect(call, `call ${n}`).toStrictEqual(g.slack[n]));
        });

        it('makes the same Jira calls, in order', () => {
          expect(review.jira.length).toBe(g.jira.length);
          review.jira.forEach((call, n) => expect(call, `call ${n}`).toStrictEqual(g.jira[n]));
        });

        it('writes the same evidence records, byte for byte', () => {
          expect(review.records).toStrictEqual(g.records.decisions);
          expect(review.tickets).toStrictEqual(g.records.tickets);
          expect(review.signoff).toStrictEqual(g.records.signoff);
        });

        it('signs the same decisions.json and hands Step Functions the same output', async () => {
          expect(review.decisionsText).toBe(g.decisions_text);
          expect(await sha256Hex(review.decisionsText ?? '')).toBe(g.decisions_sha256);
          expect(review.stepFunctions).toStrictEqual(g.step_functions);
        });

        it('prints what attest prints, intact and with each one-byte change', async () => {
          const signed = files(review);
          const changes = locate(signed);
          expect(changes).toStrictEqual(g.tampers);
          const attestation = review.attestation;
          if (!attestation) throw new Error('not signed');
          const out: Record<string, string> = {
            intact: (await attest(data.run.name, signed, attestation)).output,
          };
          for (const change of changes) {
            out[change.file] = (
              await attest(data.run.name, apply(signed, change), attestation)
            ).output;
          }
          expect(out).toStrictEqual(g.attest);
        });
      });
    }
  });
}
