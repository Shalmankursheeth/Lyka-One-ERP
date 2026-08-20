# NOTES.md

## Stack

Python + FastAPI + SQLAlchemy + SQLite. The brief allows SQLite if SQL stays portable. I used it so clone + pip + `python -m app.reset` reproduces the collision with no extra service. WAL is the only SQLite-specific piece (concurrent live write during backfill).

## Assumptions

- Survivorship is most-recent `updated` wins, whole row (Q1).
- Hyphen dates `01-02-2026` are DD-MM-YYYY, same locale as `19/07/2026` and Dubai (see traps).
- Orphan `agent_code` AG99 migrates with `agent_id = NULL` (unassigned pool) plus a warning, not quarantine — phone/name/status/deal are still confident.
- Bare `1200000` is AED, converted to fils (`x 100`), same as `"AED 1,200,000"`.
- Date-only `created` values are Asia/Dubai midnight. ISO `updated` with `Z` is UTC.
- Live writes go to the **new schema only** (revised brief). Legacy is read, never mutated by backfill or by the live path.
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

- Dual-write proxy, RUNBOOK, TIMELOG, and "tests as a scored deliverable" were cut from this brief. I kept a small pytest file so R3/R5 can be re-run without two terminals.
- `+977` digit length is unimplemented-against-real-examples.
- No auth on the live-update endpoint.

I started from the one-day zip (`lyka-cutover.zip`) by mistake, then rebuilt to this 3-hour scope: dropped the proxy/backlog, made delay sit between snapshot and write, and pointed the live path at the new schema only.

---

## Q1 — Survivorship rule, what it costs, where it is wrong in this dataset

**Rule:** most-recent legacy `updated` wins, all fields. The loser is written to `lead_merge_log` so both `legacy_id`s stay traceable.

**Cost:** "most recently touched" is treated as "most correct." Field-level "newest non-null" would keep a good value the newer row left blank; this rule will not.

**Wrong on this data:** 1001 (`Ravi Client`, updated 2026-08-01) loses to 1002 (` ravi client `, updated 2026-08-05). The surviving name is `ravi client`. That is a case/whitespace regression, not a correction. I still take 1002 because the rule is auditable and one-line; I am not pretending it improved the record.

## Q2 — R5, the ordering guarantee, 400 ms clock skew

**Guarantee:** last-writer-wins on the **stored `updated_at` value**, not on arrival order at SQLite.

**What enforces it:** every writer calls `write_candidate_lead`. Same-`legacy_id` updates are `UPDATE leads SET ... WHERE lead_id = :id AND updated_at < :candidate_ts`. If a live edit stamped `updated_at = now()` after the backfill snapshotted 1010 at `2026-08-08T09:00:00Z`, the stale UPDATE matches zero rows.

**400 ms skew:** we do not compare the backfill host clock to the API host clock. Backfill `updated_at` comes from the legacy `updated` column. Live `updated_at` comes from the API process clock at request time. Four hundred milliseconds of disagreement between those machines cannot make August 8 beat "now" on 1010. Skew only matters if two **live** writers stamp their own clocks and race within that window — first commit with the larger timestamp wins; I am not claiming to order two events that the only clock we have cannot order.

## Q3 — Where AI was used, where I did the work, where it was wrong

AI (Cursor) scaffolded models, FastAPI boilerplate, and first-pass normalisers. I chose the CAS write, the outcomes-vs-live-state split for reconciliation, the per-batch transaction (Q4), and the live path as new-schema-only.

**Where it was wrong:** the one-day runner slept *before* reading a batch, then read and wrote in one shot. That is not R5. R5 is: hold a stale snapshot, let a live write land, then attempt the stale write. Sleeping first only tests "insert Lost before 1010 exists." I caught it by lining the brief's T0/T1/T2 wording against `migrate.py` when cutting the 3-hour version, and moved the delay to after `normalize_legacy_row` and before `write_candidate_lead`. Second miss: `SIGKILL` in the interrupt test — that signal is not on Windows. The resume check uses process kill that works here.

## Q4 — The rule that is wrong and contradicts another

**R6** (one transaction for the entire migration) **contradicts R3** (kill mid-run, resume, `--batch-size`).

A single uncommitted transaction means a kill rolls everything back. There is no durable "partway" state. Resume is "start over." That can still be idempotent, but it makes `--batch-size` meaningless and makes the interrupt test indistinguishable from a fresh run. It also fights R5: a long exclusive transaction either blocks the live edit or holds locks until commit, which is not the dual-live window the collision is supposed to be.

**What I did:** implement R6 **per row**. Each `legacy_id` commits atomically; a kill loses at most the in-flight row; resume continues from `migration_outcomes`. `--batch-size` still exists so they can interrupt on a schedule (and `--crash-after-batches` in tests). Built as a resumable system, documented why a literal whole-run transaction would fail the test they said they will run. The T2 write always opens a **new** SQLite session after the delay so WAL snapshot isolation cannot hide the live edit.

---

## Q5 (optional, not scored) — production only on the VPS

1. Stop *new* undocumented VPS edits without touching the running process. The gap cannot close while it is still growing.
2. Snapshot the running tree, including `.bak` files and timestamps, and diff it against the last repo commit. That diff is the inventory. Do not redeploy yet.
3. Backport file by file into the repo, highest uncertainty first. Production keeps running what it runs until "deploy from main" is true again. Redeploying the old repo to force convergence is how you turn unknown diffs into an outage.
