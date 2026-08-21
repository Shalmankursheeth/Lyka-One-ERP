# NOTES.md

## Stack

Python + FastAPI + SQLAlchemy + **PostgreSQL** (Docker Compose on port 5433).

The brief allows SQLite. I did not use it for the assessment run. SQLite has one writer. R6 requires the whole migration to stay in one transaction. After that transaction's first write, a live `Lost` on another connection **blocks until COMMIT**. Then the live write lands *after* the backfill has already committed `Closed Won`. That is not T0/T1/T2; it is "queue the agent until the backfill is done." Postgres READ COMMITTED lets the live transaction commit while the migration transaction is still open. The backfill's next `SELECT`/`UPDATE ... WHERE updated_at < :ts` sees it. That is the collision they said they will run.

SQL stays portable (standard types, one transaction, CAS update). `DATABASE_URL` can still point at SQLite for offline normaliser experiments; do not use that for R5.

## Assumptions

- Survivorship is most-recent `updated` wins, whole row (Q1).
- Hyphen dates `01-02-2026` are DD-MM-YYYY, same locale as `19/07/2026` and Dubai (see traps).
- Orphan `agent_code` AG99 migrates with `agent_id = NULL` (unassigned pool) plus a warning, not quarantine.
- Bare `1200000` is AED, converted to fils with `Decimal`, same as `"AED 1,200,000"`.
- Date-only `created` values are Asia/Dubai midnight. ISO `updated` with `Z` is UTC.
- Live writes go to the **new schema only**. Legacy is read, never mutated by backfill or the live path.
- Nepal `+977` is 10 digits after the country code; unused in this sample.

## The ten traps

1. Three `created` formats: ISO date, `DD/MM/YYYY`, ambiguous `DD-MM-YYYY`.
2. Deal values as `"AED 1,200,000"` / `"1200000"` / empty, stored as integer fils.
3. Phones with `+`, `00`, local leading `0`, missing `+`, or too few digits (1012).
4. 1001/1002 are one lead only after E.164 — `+971 50 111 2222` vs `0501112222`.
5. 1008/1009 share a phone; 1009's name has U+00A0 so a naive equality on name would miss the duplicate.
6. U+00A0 in 1009 — `.strip()` of ASCII spaces is not enough.
7. AG99 on 1004 — dangling agent, not a blank unassigned field.
8. Empty status on 1007 — cannot default to `New`.
9. `"Meeting Done"` on 1008 — populated but not in the enum; it never enters the 1009 merge pool.
10. Truncated phone 1012 (`+971 50 333`, 5 digits after +971, expected 9).

An eleventh issue is in the rules, not the rows — Q4.

## Twelve-row ledger

| legacy_id | bucket | detail |
|---|---|---|
| 1001 | merged | lost to 1002, same phone `+971501112222`, 1002 `updated` is later |
| 1002 | migrated | survivor of 1001/1002 |
| 1003 | migrated | `19/07/2026` is unambiguously DD/MM |
| 1004 | migrated | `agent_id` NULL — AG99 missing (warning, not quarantine) |
| 1005 | migrated | `01-02-2026` → 1 Feb 2026 via DD-MM locale rule |
| 1006 | migrated | `00971...` → `+971509876543` |
| 1007 | quarantined | status empty; enum has no default |
| 1008 | quarantined | status `Meeting Done` not in enum |
| 1009 | migrated | NBSP collapsed; 1008 never entered the duplicate pool |
| 1010 | migrated | collision-test row |
| 1011 | migrated | `971561112233` inferred as +971 |
| 1012 | quarantined | phone has 5 digits after +971, expected 9 |

**8 + 1 + 3 = 12.**

## What I did not finish

- Dual-write proxy, RUNBOOK, TIMELOG were cut from this brief.
- `+977` digit length is unimplemented-against-real-examples.
- No auth on the live-update endpoint.

---

## Q1 — Survivorship rule, what it costs, where it is wrong in this dataset

**Rule:** most-recent legacy `updated` wins, all fields. The loser is written to `lead_merge_log` so both `legacy_id`s stay traceable.

**Cost:** "most recently touched" is treated as "most correct." Field-level "newest non-null" would keep a good value the newer row left blank; this rule will not.

**Wrong on this data:** 1001 (`Ravi Client`, updated 2026-08-01) loses to 1002 (` ravi client `, updated 2026-08-05). The surviving name is `ravi client`. That is a case/whitespace regression, not a correction. I still take 1002 because the rule is auditable and one-line; I am not pretending it improved the record.

## Q2 — R5, the ordering guarantee, 400 ms clock skew

**Guarantee:** last-writer-wins on the **stored `updated_at` value**, not on arrival order.

**What enforces it:** every writer calls `write_candidate_lead`. Same-`legacy_id` updates are `UPDATE leads SET ... WHERE lead_id = :id AND updated_at < :candidate_ts`. After the delay, the migration session does `expire_all()` so the next SELECT (Postgres READ COMMITTED) sees a live commit. If 1010 is already `Lost` with `updated_at = now()`, the stale Closed Won snapshot matches zero rows.

**400 ms skew:** we do not compare the backfill host clock to the API host clock. Backfill `updated_at` comes from the legacy `updated` column. Live `updated_at` comes from the API process clock at request time. Four hundred milliseconds of disagreement cannot make 8 Aug beat "now" on 1010.

## Q3 — Where AI was used, where I did the work, where it was wrong

AI scaffolded models, FastAPI boilerplate, and first-pass normalisers. I chose CAS, reconciliation from live tables rather than trusting a checkpoint, Postgres for R5+R6, and the live path as new-schema-only.

**Where it was wrong:** the first 3-hour runner committed **per row** and called that "R6 per batch." That is not R6. A second model called that out against the brief. The delay used to sit on a *new* SQLite session after COMMIT so the live write was visible — which only worked because we had already abandoned one-transaction R6. I implemented R6 as a single COMMIT, moved R3 to restart-and-converge, and switched the collision DB to Postgres so the live write is a real second transaction, not an in-process hook.

## Q4 — The rule that is wrong and contradicts another

**R6** ("the entire migration must execute inside a single database transaction") **contradicts R3** as written ("we will kill your process partway through and restart it" plus `--batch-size`).

Implemented R6 literally: `BEGIN`; process every source row (normalise, quarantine, merge, outcomes); **one `COMMIT`**. No intermediate commits. Kill before COMMIT rolls the whole thing back. Target schema is untouched.

R3 in that world cannot mean "checkpoint resume." There is nothing durable to resume from. R3 means **restart-and-converge**: kill → rollback → run the migrator again over the same source → idempotent writes → same final state as an uninterrupted run. Three complete runs match one because every write is a CAS / upsert, not because we skipped ids in a checkpoint table.

`--batch-size` is only the delay cadence for the R5 window, not a commit boundary.

I did not weaken R6 to make R5 easier. SQLite cannot interleave a live writer inside that transaction; Postgres can. That is why the stack is Postgres.

---

## Q5 (optional, not scored) — production only on the VPS

1. Stop *new* undocumented VPS edits without touching the running process.
2. Snapshot the running tree, including `.bak` files and timestamps, and diff it against the last repo commit.
3. Backport file by file into the repo, highest uncertainty first. Do not redeploy the old repo to force convergence.
