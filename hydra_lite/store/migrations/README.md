# Schema migrations

`../schema.sql` is the frozen v1 schema; never edit it. Change the database by adding `NNNN_short_name.sql` here
(`0002`, `0003`, ... with no gaps). Each file runs in one transaction after the database is copied to
`hydra.db.pre-v<N>.bak`; the runner sets `PRAGMA user_version` for you. Keep migrations additive where possible,
and extend `tests/lite/test_migrations.py` (the committed `tests/fixtures/lite_v1.db` must still upgrade).
