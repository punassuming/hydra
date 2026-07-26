# Operator UI journey

This guide maps the day-to-day operator path through Hydra's browser UI. It is
written for a domain operator; an admin token adds domain and credential
management but is not needed to submit or observe work.

## Sign in

1. Open the Hydra UI and enter the target **Domain** and its **Domain Token**.
2. Optionally enter an **Admin Token** when the session needs cross-domain or
   administrative access.
3. Select **Connect**. The UI validates the domain token before saving it in
   the browser and opening the **Operate** view.

The domain/token pair is also what a worker uses to join that domain. Treat it
as a credential: use a short-lived test token for local demos and never put a
production token in screenshots, docs, or browser tests.

## Submit and run a job

1. In **Operate**, select **New Job**.
2. Give the job a descriptive name, select an executor, and enter its command
   or code. A shell job defaults to a Linux `bash` worker and a short
   `echo 'hello world'` command.
3. Keep the default **Immediate** schedule for a one-time submission, or
   choose a recurring/dependency schedule as appropriate.
4. Select **Validate & Submit**. Validation runs before the definition is
   stored; errors remain in the form for correction.
5. Select the new job in the jobs table to inspect its history. For a saved
   definition, **Run Now** queues another execution without editing it.

Use **Run Non-Persistent** only for a disposable execution: it runs the
current form payload once and does not save a job definition.

## Observe execution and logs

- **Operate** provides the job list, current queue health, upcoming work, and
  job-specific history.
- **Observe** is the cross-job run history. Filter runs by job, worker, user,
  or status, then choose **View Logs** for stdout/stderr and timing details.
- A running job streams log output in the log dialog. A completed job displays
  its persisted log tail; the same dialog exposes the AI log helper when an AI
  provider is configured.

If work remains queued, check queue health first, then move to **Workers** to
confirm that an eligible worker is online and has the executor capability the
job requires.

## Operate workers

The **Workers** view shows connectivity, dispatch state, capabilities,
capacity, and recent activity. Open a worker for its metrics, execution
timeline, and operations history. Use draining/offline states before planned
maintenance; use detach only for an offline worker record after confirming its
queued work has been requeued.

## CI coverage

The browser journey is intentionally split into two layers:

- A Cypress browser check signs in to the seeded `ci` domain and verifies the
  Operate, Observe, and Workers views against the real Compose stack.
- The existing full-stack API smoke test submits a shell job, waits for the
  worker result, and verifies persisted output. Together they keep the
  credential boundary, navigation, job dispatch, and log persistence covered
  without putting a real token into CI.

For local browser exploration, start the Compose stack with a disposable
domain token, then use the same journey above. Playwright is useful for
capturing screenshots and accessibility snapshots; Cypress is used in CI
because it is already a locked project dependency.
