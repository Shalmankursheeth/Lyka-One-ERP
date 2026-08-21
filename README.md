# Lyka One — the cutover (revised 3-hour brief)

Python + FastAPI + SQLAlchemy + SQLite. No Postgres daemon. Reviewer can clone, install, and run the collision on a laptop.

This is the **revised 3-hour** scope: schemas + seed, resumable migration, one live write path into the new schema, reconciliation. Not in this repo (deliberately cut): dual-write proxy, cutover runbook, TIMELOG.

## Setup

```powershell
git clone https://github.com/Shalmankursheeth/Lyka-One-ERP.git
cd Lyka-One-ERP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Reset to clean (we will use this repeatedly)

```powershell
python -m app.reset
```

That drops every table, recreates the schema, and seeds 5 agents + 12 legacy leads. Row 1009's name is seeded with a real U+00A0.

## 1. Migration runner

```powershell
python -m app.reset
python -m app.migrate --batch-size 1
```

`--batch-size` is the commit boundary. `--delay-seconds` injects sleep **after the legacy row is snapshotted and before it is written** — that is the T0/T2 window.

Interrupt and resume:

```powershell
python -m app.reset
python -m app.migrate --batch-size 1 --delay-seconds 2
# Ctrl+C (or kill the process) after a few rows print / after a few seconds
python -m app.migrate --batch-size 1
python -m app.reconcile
```

The second run skips `legacy_id`s already in `migration_outcomes` and converges to the same ledger as an uninterrupted run.

## 2. Survive the collision (R5)

Exact commands. Two terminals, same machine, same DB.

**Terminal A**

```powershell
python -m app.reset
python -m app.migrate --batch-size 1 --delay-seconds 3
```

**Terminal B** — run as soon as A is sleeping (do not wait for A to finish):

```powershell
python -m app.live_update --legacy-id 1010 --status Lost
```

Let A finish. Then:

```powershell
python -m app.reconcile
```

Lead 1010 must be `Lost`, not `Closed Won`.

Same thing over HTTP if you prefer:

```powershell
python -m uvicorn app.main:app --port 8000
```

```powershell
curl -X POST http://127.0.0.1:8000/api/leads/1010/update -H "Content-Type: application/json" -d "{\"status\":\"Lost\"}"
```

## 3. Reconciliation

```powershell
python -m app.reconcile
```

Expect **8 migrated + 1 merged + 3 quarantined = 12**. If the buckets do not sum to 12, a row was dropped.

## Optional checks

```powershell
python -m pytest tests -q
```

Automated tests were cut from the revised brief. They are here only so R3/R5 can be re-run without two terminals.
