# OpenClaw integration

`HydraClient` binds every request to one API token and one domain using
`x-api-key` and `x-domain`. Construct a separate client with an admin token
for `rotate_token`; rotation calls `/domain/token/rotate` and revokes the previous domain token.

The acceptance jobs in `jobs/acceptance.yaml` are source-controlled and
harmless: one echo job covers submit/run/history/log retrieval, while the
second covers timeout handling. Retry behavior is represented by
`max_retries: 1`; cancellation uses `POST /runs/{run_id}/kill`.

Live execution is intentionally a gated operation. Run the repository
acceptance suite only after deployment approval; no credentials belong in
this directory.
