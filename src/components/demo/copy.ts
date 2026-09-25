// The demo's own words, in one place. Everything the simulated Slack and Jira show comes from
// the tool's export instead. Copy Matthew hasn't approved starts with "DRAFT:" (CLAUDE.md
// rule 6), and a dist test fails while any is left in the built JavaScript.

export const copy = {
  title: 'Be the CISO',
  intro:
    "DRAFT: You're the CISO at Acme, a fictional company, and the quarterly access review just " +
    'opened. Decide every item, sign off, and see the tickets it opens. Then change one byte of ' +
    'the evidence and watch the check catch it.',
  honest:
    'DRAFT: Nothing here is mocked up. The review, the messages and the tickets are the output ' +
    "of the tool's own code at one commit, and this page replays them. A test checks the replay " +
    'matches the tool byte for byte.',
  start: 'Start the review',
  startOver: 'Start over',
  stepOf: (n: number, total: number) => `Step ${n} of ${total}`,
  aws: 'What AWS does here',
  badges: {
    dm: 'Simulated Slack DM',
    channel: 'Simulated Slack channel',
    jira: 'Simulated Jira ticket',
    terminal: "The tool's own check",
  },
  steps: {
    open: {
      title: 'The review opens',
      body:
        'DRAFT: The review channel gets counts only. Names and details go to your DM, the report ' +
        'and Jira. Two people HR says have left can still get in, so their tickets are already open.',
      aws:
        'DRAFT: EventBridge Scheduler starts the review workflow in Step Functions. A Lambda ' +
        'function reads Okta (read only) and writes the review to S3, every file hashed in a ' +
        'manifest and kept create only under Object Lock. Another opens the Jira tickets, sends ' +
        'your DM, and the workflow waits for your sign-off.',
      next: 'Open your DM',
    },
    decide: {
      title: 'Decide every item',
      body:
        'DRAFT: Each card shows the facts, why it could be an issue, and a proposal. Confirm ' +
        'accepts every proposal at once. Keeping something proposed for revocation, or ' +
        'overriding a proposal, asks for a reason.',
      aws:
        "DRAFT: Each click goes to a Lambda function URL that checks Slack's signature first. " +
        "The decision is written to S3 as a record that can't be changed. Changing your mind " +
        'adds a newer record, and the latest one wins.',
      next: 'Review the list and sign off',
    },
    signoff: {
      title: 'Sign off',
      body:
        "DRAFT: Every decision in one list, bound to the manifest's SHA-256. Check it, then " +
        'approve.',
      aws:
        'DRAFT: Approving writes the final decisions and a sign-off record bound to two hashes: ' +
        "the manifest's and the decisions'. Then the waiting workflow picks up again.",
    },
    done: {
      title: 'The tickets',
      body:
        'DRAFT: Signed off. One Jira ticket for each revoke and each finding to fix, with the ' +
        'checklist in your DM and a summary in the channel.',
      aws:
        'DRAFT: The workflow opens the tickets from the signed decisions, never from a new count. ' +
        'Each day a Lambda function reads Okta again and ticks off the fixes it can see.',
      next: 'Check the evidence',
    },
    evidence: {
      title: 'Check the evidence',
      body:
        "DRAFT: An auditor downloads the review from S3 and runs the tool's check. Your " +
        'browser hashes the files right here. Change one byte and see what it says.',
      aws:
        'DRAFT: Everything the review wrote sits in S3 under Object Lock. The check hashes each ' +
        'file against the manifest, and the sign-off against both hashes.',
      scope:
        "DRAFT: This page holds three of the files and hashes those. The run's other six files " +
        "aren't on the page, so here they count as matching.",
      run: 'Run the check',
      restore: 'Put it back',
      change: 'Change one byte',
    },
  },
  progress: (decided: number, total: number) => `${decided} of ${total} decided`,
  confirmAll: (n: number) => `Confirm ${n} proposed`,
  reasonLabel: 'Why?',
  reasonLimit: (n: number, max: number) => `${n} of ${max} characters`,
  tooLong: (max: number) => `Keep it to ${max} characters here.`,
  cancel: 'Cancel',
  ciso: 'You (CISO)',
  bot: 'Access review',
  pdf: (name: string) => `${name} (the report, in this thread)`,
  source: (commit: string) => `The tool at commit ${commit.slice(0, 7)}`,
  sample: 'Sample report (PDF)',
} as const;
