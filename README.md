# Lyka One — the cutover (revised 3-hour brief)

Python + FastAPI + SQLAlchemy + **PostgreSQL**. SQLite is allowed by the brief, but it cannot honestly do R5 inside R6: one migration transaction takes the only writer lock, so a live update either blocks until COMMIT or never interleaves. Postgres READ COMMITTED lets the live write commit while the backfill transaction is still open. That is the collision the evaluator will run.

Scope: migration runner, one live write into the new schema, reconciliation, README, NOTES Q1–Q4. No dual-write proxy, runbook, or backlog.

## Setup

```powershell
git clone https://github.com/Shalmankursheeth/Lyka-One-ERP.git
cd Lyka-One-ERP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d --wait
```

Default URL: `postgresql+psycopg://lyka:lyka@127.0.0.1:5433/lyka` (compose maps 5433 → 5432). Override with `DATABASE_URL` if needed.

## Reset to clean (we will use this repeatedly)

```powershell
python -m app.reset
```

Drops every table, recreates the schema, seeds 5 agents + 12 legacy leads. Row 1009's name is a real U+00A0.

## 1. Migration runner

R6: the whole run is **one transaction**. `--batch-size` is only how many rows between delay sleeps. It is not a commit size.

```powershell
python -m app.reset
python -m app.migrate --batch-size 1
python -m app.reconcile
```

Interrupt and restart (R3 = restart-and-converge, not checkpoint resume):

```powershell
python -m app.reset
python -m app.migrate --batch-size 1 --delay-seconds 2
# kill the process after a few seconds (Ctrl+C)
python -m app.migrate --batch-size 1
python -m app.reconcile
```

After the kill, target tables are empty (the uncommitted transaction rolled back). The second run reads the source again and finishes in the same state as an uninterrupted run.

## 2. Survive the collision (R5)

Two terminals, same Postgres.

**Terminal A**

```powershell
python -m app.reset
python -m app.migrate --batch-size 1 --delay-seconds 3
```

**Terminal B** — while A is still running (do not wait for A to finish):

```powershell
python -m app.live_update --legacy-id 1010 --status Lost
```

Let A finish. Then:

```powershell
python -m app.reconcile
```

Lead 1010 must be `Lost`, not `Closed Won`.

HTTP equivalent of the live path:

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

Expect **8 migrated + 1 merged + 3 quarantined = 12**.

## Optional checks

```powershell
python -m pytest tests -q
```
