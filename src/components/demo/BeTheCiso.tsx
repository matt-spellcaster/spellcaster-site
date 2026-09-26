// "Be the CISO": the tool's review, replayed in the browser from its own export
// (src/data/demo/). The engine in src/lib/demo/ does what the tool does, byte for byte; this
// file only draws it. Nothing here makes a network request.

import {
  Component,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import raw from '../../data/demo/web.json';
import {
  apply,
  attest,
  locate,
  type Checked,
  type Files,
  type Located,
} from '../../lib/demo/evidence';
import { len } from '../../lib/demo/py';
import {
  approve,
  confirm,
  confirmable,
  DecisionError,
  DEMO_REASON_MAX,
  openReview,
  progress,
  reasonRequired,
  record,
  type Review,
} from '../../lib/demo/review';
import { reasonModalText } from '../../lib/demo/slack';
import {
  ACKNOWLEDGE_ONLY,
  isPost,
  type Button,
  type DemoData,
  type Item,
  type JiraCall,
  type SlackPayload,
} from '../../lib/demo/types';
import { copy } from './copy';
import { Adf, Blocks, Frame, Message } from './Frames';
import { Mrkdwn } from './Mrkdwn';

const data = raw as unknown as DemoData;
const STAGES = ['setup', 'open', 'decide', 'signoff', 'done', 'evidence'] as const;
type Stage = (typeof STAGES)[number];
const REPO = `https://github.com/${data.source.repo}`;

type Dialog =
  | { kind: 'reason'; item: Item; decision: string }
  | { kind: 'confirm'; button: Button }
  | { kind: 'approve'; button: Button };

const PRIMARY =
  'bg-accent text-canvas hover:bg-ink inline-flex min-h-11 items-center rounded-lg px-4 font-sans text-sm font-medium transition-colors disabled:opacity-60';
const SECONDARY =
  'border-line text-ink hover:bg-surface-2 inline-flex min-h-11 items-center rounded-lg border px-4 font-sans text-sm font-medium transition-colors';
// A one-byte change: what it does, then where, stacked on a phone.
const TAMPER =
  'border-line text-ink hover:bg-surface-2 aria-pressed:border-revoke aria-pressed:bg-surface-2 flex min-h-11 w-full flex-col items-start gap-1 rounded-lg border px-4 py-2.5 text-left font-sans text-sm font-medium transition-colors sm:flex-row sm:items-center sm:justify-between';
const BOX = 'demo border-line bg-canvas my-8 rounded-2xl border p-4 sm:p-6';

// --- dialogs ----------------------------------------------------------------------------

function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-label={title}
      className="bg-surface border-line text-ink backdrop:bg-canvas/80 m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border p-0 font-sans"
    >
      {open && (
        <div className="p-5">
          <h4 className="text-ink text-base font-semibold">{title}</h4>
          {children}
        </div>
      )}
    </dialog>
  );
}

function ReasonForm({
  item,
  decision,
  onSubmit,
  onCancel,
}: {
  item: Item;
  decision: string;
  onSubmit: (reason: string) => string | null;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const n = len(reason);
  return (
    <form
      className="mt-3 space-y-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setError(n > DEMO_REASON_MAX ? copy.tooLong(DEMO_REASON_MAX) : onSubmit(reason));
      }}
    >
      <Mrkdwn
        text={reasonModalText(item, decision, data.settings.max_text)}
        className="text-ink/85"
      />
      <label className="block">
        <span className="text-ink font-medium">{copy.reasonLabel}</span>
        <input
          type="text"
          value={reason}
          autoComplete="off"
          aria-invalid={error ? true : undefined}
          aria-describedby="demo-reason-help"
          onChange={(e) => setReason(e.target.value)}
          className="border-line bg-canvas text-ink focus:border-accent mt-1.5 block min-h-11 w-full rounded-lg border px-3"
        />
      </label>
      <p
        id="demo-reason-help"
        className={error ? 'text-revoke' : 'text-muted'}
        role={error ? 'alert' : undefined}
      >
        {error ?? copy.reasonLimit(n, DEMO_REASON_MAX)}
      </p>
      <div className="flex justify-end gap-2">
        <button type="button" className={SECONDARY} onClick={onCancel}>
          {copy.cancel}
        </button>
        <button type="submit" className={PRIMARY}>
          {decision === 'keep' ? 'Keep' : 'Revoke'}
        </button>
      </div>
    </form>
  );
}

function ConfirmForm({
  button,
  busy,
  onConfirm,
  onCancel,
}: {
  button: Button;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const c = button.confirm;
  if (!c) return null;
  return (
    <div className="mt-3 space-y-4 text-sm">
      <Mrkdwn text={c.text.text} className="text-ink/85" />
      <div className="flex justify-end gap-2">
        <button type="button" className={SECONDARY} onClick={onCancel}>
          {c.deny.text}
        </button>
        <button type="button" className={PRIMARY} disabled={busy} onClick={onConfirm}>
          {c.confirm.text}
        </button>
      </div>
    </div>
  );
}

// --- pieces -----------------------------------------------------------------------------

/** A disclosure on phones, a side column on wide screens. */
function Aws({ text, wide }: { text: string; wide: boolean }) {
  return wide ? (
    <aside className="font-sans text-sm">
      <p className="eyebrow">{copy.aws}</p>
      <p className="text-muted mt-2 leading-relaxed">{text}</p>
    </aside>
  ) : (
    <details className="border-line mb-4 rounded-lg border px-4 font-sans text-sm">
      <summary className="disclosure text-ink flex min-h-11 cursor-pointer items-center font-medium">
        {copy.aws}
      </summary>
      <p className="text-muted pb-3 leading-relaxed">{text}</p>
    </details>
  );
}

function Tickets({ calls, label }: { calls: JiraCall[]; label: string }) {
  const created = calls.filter((c) => c.call === 'create');
  return (
    <Frame badge={copy.badges.jira} title={label}>
      <ul className="divide-line -my-2 divide-y text-sm">
        {created.map((c) => (
          <li key={c.key}>
            <details>
              <summary className="disclosure flex min-h-11 cursor-pointer items-center gap-2 py-2">
                <span className="text-accent font-mono text-xs">{c.key}</span>
                <span className="text-ink min-w-0 flex-1 break-words">{c.fields.summary}</span>
                <span className="text-muted shrink-0 text-xs">due {c.fields.duedate}</span>
              </summary>
              <div className="text-ink/85 pb-3 leading-relaxed">
                <Adf doc={c.fields.description} />
              </div>
            </details>
          </li>
        ))}
      </ul>
    </Frame>
  );
}

function Terminal({ text, code }: { text: string; code: number }) {
  return (
    <pre
      className={`bg-canvas mt-3 overflow-hidden rounded-lg border p-4 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap ${code ? 'border-revoke text-ink' : 'border-keep text-ink'}`}
    >
      {text}
    </pre>
  );
}

// --- the demo ---------------------------------------------------------------------------

/** If the demo breaks, it says so and points at the screenshots, rather than going blank. */
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override render() {
    return this.state.failed ? (
      <div className={BOX}>
        <p role="alert" className="text-ink/85 font-sans text-sm leading-relaxed">
          {copy.broken}
        </p>
      </div>
    ) : (
      this.props.children
    );
  }
}

export default function BeTheCiso() {
  return (
    <Boundary>
      <Demo />
    </Boundary>
  );
}

const noop = () => () => {};

function Demo() {
  // False in the server's HTML and until the island has hydrated, so Start does nothing it
  // can't do: without JavaScript, the page points at the screenshots instead.
  const live = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  const [stage, setStage] = useState<Stage>('setup');
  const [review, setReview] = useState<Review>(() => openReview(data));
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [announce, setAnnounce] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState<{ change: Located | null; result: Checked } | null>(null);
  // Anything but the tool's own refusal is a bug, or a browser that can't hash: the boundary
  // above draws it, since it can't catch what an event handler throws.
  const [crash, setCrash] = useState<{ error: unknown } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const dm = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  // The item just decided ('' for Confirm), for the focus to move on from.
  const decided = useRef<string | null>(null);
  // Sign-off and the check hash in the background. Start over, or a newer check, bumps this,
  // so a result that lands late is dropped instead of drawn over the new state.
  const generation = useRef(0);

  // Each step starts at its heading: scrolled to the top (below the fixed header, through
  // scroll-padding-top) and focused, so a screen reader starts reading there too.
  useEffect(() => {
    if (!moved.current) return;
    heading.current?.scrollIntoView({ block: 'start' });
    heading.current?.focus({ preventScroll: true });
  }, [stage]);

  // A decision takes its buttons away, so focus goes on to the next item below that needs
  // one (then round to the top), or to what comes next once none do.
  useEffect(() => {
    const after = decided.current;
    if (after === null) return;
    decided.current = null;
    const groups = [
      ...(dm.current?.querySelectorAll<HTMLElement>('[role="group"][data-item]') ?? []),
    ];
    const at = groups.findIndex((g) => g.dataset['item'] === after);
    const next =
      [...groups.slice(at + 1), ...groups.slice(0, at + 1)]
        .map((g) => g.querySelector<HTMLElement>('button'))
        .find((b) => b) ?? bar.current?.querySelector<HTMLElement>('button');
    next?.focus();
  }, [review]);

  const go = (next: Stage) => {
    moved.current = true;
    setError(null);
    setStage(next);
    const n = STAGES.indexOf(next);
    if (n > 0) setAnnounce(`${copy.stepOf(n, STAGES.length - 1)}`);
  };

  const startOver = () => {
    generation.current++;
    setReview(openReview(data));
    setDialog(null);
    setChecked(null);
    go('setup');
  };

  if (crash) throw crash.error;

  const count = progress(review);
  const said = (r: Review) => copy.progress(progress(r).decided, progress(r).total);

  /** Record one click; the tool's own refusal comes back as a message. */
  const decide = (item: Item, decision: string, reason: string): string | null => {
    try {
      const next = record(review, [[item.key, decision, reason]]).review;
      decided.current = item.key;
      setReview(next);
      setDialog(null);
      setError(null);
      const done = ACKNOWLEDGE_ONLY.includes(item.kind)
        ? 'Acknowledged'
        : decision === 'keep'
          ? 'Kept'
          : 'Revoked';
      setAnnounce(`${done}: ${item.target} for ${item.user}. ${said(next)}.`);
      return null;
    } catch (e) {
      if (e instanceof DecisionError) return e.message;
      setCrash({ error: e });
      return null;
    }
  };

  const onAction = (button: Button) => {
    if (button.action_id === 'confirm_proposed' || button.action_id === 'approve') {
      setDialog({ kind: button.action_id === 'approve' ? 'approve' : 'confirm', button });
      return;
    }
    const { k } = JSON.parse(button.value) as { k: string };
    const item = review.byKey[k];
    const decision = button.action_id.split(':')[1] ?? '';
    if (!item) return;
    if (reasonRequired(item, decision)) setDialog({ kind: 'reason', item, decision });
    else setError(decide(item, decision, ''));
  };

  const confirmAll = () => {
    try {
      const next = confirm(review).review;
      decided.current = '';
      setReview(next);
      setAnnounce(`${said(next)}.`);
    } catch (e) {
      if (e instanceof DecisionError) setError(e.message);
      else setCrash({ error: e });
    }
    setDialog(null);
  };

  const signOff = async () => {
    const id = generation.current;
    setBusy(true);
    try {
      const next = (await approve(review)).review;
      if (id !== generation.current) return;
      setReview(next);
      setDialog(null);
      go('done');
    } catch (e) {
      if (id !== generation.current) return;
      if (e instanceof DecisionError) setError(e.message);
      else setCrash({ error: e });
      setDialog(null);
    } finally {
      setBusy(false);
    }
  };

  const files = (): Files => ({
    'manifest.json': data.run.manifest_text,
    'review_items.json': data.run.items_text,
    'signoff/decisions.json': review.decisionsText ?? '',
  });

  const check = async (change: Located | null) => {
    if (!review.attestation) return;
    const id = ++generation.current;
    let result: Checked;
    try {
      result = await attest(
        data.run.name,
        change ? apply(files(), change) : files(),
        review.attestation,
      );
    } catch (e) {
      if (id === generation.current) setCrash({ error: e });
      return;
    }
    if (id !== generation.current) return;
    setChecked({ change, result });
    setAnnounce(result.code ? `The check failed: ${change?.why}.` : 'The check passed.');
  };

  const msg = (ts: string | null): SlackPayload | undefined =>
    ts ? review.messages[ts] : undefined;
  const channelPost = data.open.slack
    .filter(isPost)
    .find((c) => c.channel === data.settings.channel);
  const n = STAGES.indexOf(stage);

  const step = (title: string, body: string, aws: string, children: ReactNode) => (
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_13rem] lg:gap-8">
      <div className="min-w-0">
        <p className="eyebrow">{copy.stepOf(n, STAGES.length - 1)}</p>
        <h3
          ref={heading}
          tabIndex={-1}
          className="text-ink mt-2 font-serif text-2xl font-medium outline-none"
        >
          {title}
        </h3>
        <p className="text-ink/85 mt-2 mb-5 text-lg leading-relaxed">{body}</p>
        <div className="lg:hidden">
          <Aws text={aws} wide={false} />
        </div>
        <div className="space-y-5">{children}</div>
      </div>
      <div className="hidden lg:sticky lg:top-24 lg:block lg:self-start">
        <Aws text={aws} wide />
      </div>
    </div>
  );

  let view: ReactNode;
  if (stage === 'setup') {
    view = (
      <div>
        <h3 ref={heading} tabIndex={-1} className="sr-only outline-none">
          {copy.title}
        </h3>
        <p className="text-ink/85 text-lg leading-relaxed">{copy.intro}</p>
        <p className="text-muted mt-3 font-sans text-sm leading-relaxed">{copy.honest}</p>
        {!live && (
          <p className="text-muted mt-3 font-sans text-sm leading-relaxed">{copy.waiting}</p>
        )}
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="button" className={PRIMARY} disabled={!live} onClick={() => go('open')}>
            {copy.start}
          </button>
          <a className={SECONDARY} href={`${REPO}/tree/${data.source.commit}`}>
            {copy.source(data.source.commit)}
          </a>
        </div>
      </div>
    );
  } else if (stage === 'open') {
    const s = copy.steps.open;
    view = step(
      s.title,
      s.body,
      s.aws,
      <>
        {channelPost && (
          <Frame badge={copy.badges.channel} title="#access-review">
            <Message>
              <Blocks payload={channelPost.payload} />
            </Message>
          </Frame>
        )}
        <Tickets calls={data.open.jira} label={`${data.settings.jira_project} project`} />
        <button type="button" className={PRIMARY} onClick={() => go('decide')}>
          {s.next}
        </button>
      </>,
    );
  } else if (stage === 'decide') {
    const s = copy.steps.decide;
    const left = confirmable(review).length;
    view = step(
      s.title,
      s.body,
      s.aws,
      <>
        <div ref={dm}>
          <Frame badge={copy.badges.dm} title={copy.bot}>
            {[review.summaryTs, ...review.chunkTs].map((ts) => {
              const payload = msg(ts);
              return payload ? (
                <Message key={ts}>
                  <Blocks payload={payload} items={review.byKey} onAction={onAction} />
                </Message>
              ) : null;
            })}
          </Frame>
        </div>
        <div
          ref={bar}
          className="border-line bg-canvas sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-3 border-t px-1 py-3 font-sans text-sm"
        >
          <span className="text-ink font-medium">{copy.progress(count.decided, count.total)}</span>
          {left > 0 && (
            <button
              type="button"
              className={SECONDARY}
              onClick={() => {
                const button = msg(review.summaryTs)?.blocks.flatMap((b) =>
                  b.type === 'actions' ? b.elements : [],
                )[0];
                if (button) setDialog({ kind: 'confirm', button });
              }}
            >
              {copy.confirmAll(left)}
            </button>
          )}
          {count.open === 0 && (
            <button type="button" className={PRIMARY} onClick={() => go('signoff')}>
              {s.next}
            </button>
          )}
        </div>
      </>,
    );
  } else if (stage === 'signoff') {
    const s = copy.steps.signoff;
    const payload = msg(review.approveTs);
    view = step(
      s.title,
      s.body,
      s.aws,
      <Frame badge={copy.badges.dm} title={copy.bot}>
        {payload && (
          <Message>
            <Blocks payload={payload} onAction={onAction} disabled={busy} />
            <p className="border-line text-muted rounded-lg border px-3 py-2 text-xs">
              📄 {copy.pdf(`okta-access-review-${data.run.name}.pdf`)}
            </p>
          </Message>
        )}
      </Frame>,
    );
  } else if (stage === 'done') {
    const s = copy.steps.done;
    const signed = msg(review.approveTs);
    const checklist = msg(review.checklistTs);
    const finished = msg(review.finishedTs);
    view = step(
      s.title,
      s.body,
      s.aws,
      <>
        <Frame badge={copy.badges.dm} title={copy.bot}>
          {signed && (
            <Message>
              <Blocks payload={signed} />
            </Message>
          )}
          {checklist && (
            <div className="border-line ml-4 border-l pl-3">
              <Message>
                <Blocks payload={checklist} />
              </Message>
            </div>
          )}
        </Frame>
        {finished && (
          <Frame badge={copy.badges.channel} title="#access-review">
            <Message>
              <Blocks payload={finished} />
            </Message>
          </Frame>
        )}
        <Tickets calls={review.jira} label={`${data.settings.parent_issue} sub-tasks`} />
        <button type="button" className={PRIMARY} onClick={() => go('evidence')}>
          {s.next}
        </button>
      </>,
    );
  } else {
    const s = copy.steps.evidence;
    const changes = review.decisionsText ? locate(files()) : [];
    view = step(
      s.title,
      s.body,
      s.aws,
      <>
        <p className="text-muted font-sans text-sm leading-relaxed">{s.scope}</p>
        <div className="flex flex-wrap gap-3">
          <button type="button" className={PRIMARY} onClick={() => void check(null)}>
            {checked?.change ? s.restore : s.run}
          </button>
        </div>
        <fieldset className="font-sans text-sm">
          <legend className="text-ink font-medium">{s.change}</legend>
          <div className="mt-2 flex flex-col gap-2">
            {changes.map((c) => (
              <button
                key={c.file}
                type="button"
                aria-pressed={checked?.change?.file === c.file}
                className={TAMPER}
                onClick={() => void check(c)}
              >
                <span>{c.why}</span>
                <span className="text-muted font-mono text-xs sm:ml-3">
                  {c.file} byte {c.offset}: {c.from} → {c.to}
                </span>
              </button>
            ))}
          </div>
        </fieldset>
        {checked && (
          <Frame
            badge={copy.badges.terminal}
            title={`access-review attest reports/${data.run.name}`}
          >
            <dl className="text-muted grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono text-xs">
              <dt>manifest.json</dt>
              <dd className="break-all">{checked.result.manifestSha256}</dd>
              <dt>review_items.json</dt>
              <dd className="break-all">{checked.result.itemsSha256}</dd>
              <dt>decisions.json</dt>
              <dd className="break-all">{checked.result.decisionsSha256}</dd>
            </dl>
            <Terminal text={checked.result.output} code={checked.result.code} />
          </Frame>
        )}
        <div className="flex flex-wrap gap-3">
          <a className={SECONDARY} href={`${REPO}/tree/${data.source.commit}`}>
            {copy.source(data.source.commit)}
          </a>
          <a
            className={SECONDARY}
            href={`${REPO}/blob/${data.source.commit}/docs/sample-report.pdf`}
          >
            {copy.sample}
          </a>
        </div>
      </>,
    );
  }

  return (
    <div className={BOX}>
      {stage !== 'setup' && (
        <div className="border-line mb-5 flex items-center justify-between gap-3 border-b pb-3 font-sans text-sm">
          <span className="text-muted">{copy.title}</span>
          <button type="button" className={SECONDARY} onClick={startOver}>
            {copy.startOver}
          </button>
        </div>
      )}
      {view}
      {error && (
        <p role="alert" className="text-revoke mt-4 font-sans text-sm">
          {error}
        </p>
      )}
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      <Modal open={dialog?.kind === 'reason'} title="Reason needed" onClose={() => setDialog(null)}>
        {dialog?.kind === 'reason' && (
          <ReasonForm
            item={dialog.item}
            decision={dialog.decision}
            onSubmit={(reason) => decide(dialog.item, dialog.decision, reason)}
            onCancel={() => setDialog(null)}
          />
        )}
      </Modal>
      <Modal
        open={dialog?.kind === 'confirm' || dialog?.kind === 'approve'}
        title={
          dialog?.kind === 'confirm' || dialog?.kind === 'approve'
            ? (dialog.button.confirm?.title.text ?? '')
            : ''
        }
        onClose={() => setDialog(null)}
      >
        {(dialog?.kind === 'confirm' || dialog?.kind === 'approve') && (
          <ConfirmForm
            button={dialog.button}
            busy={busy}
            onConfirm={() => (dialog.kind === 'approve' ? void signOff() : confirmAll())}
            onCancel={() => setDialog(null)}
          />
        )}
      </Modal>
    </div>
  );
}
