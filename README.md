# Lakebase Support App

Day 1 Homework: a small Databricks App backed by Lakebase (Databricks-managed
Postgres) that implements a support ticketing system.

## Schema

- **tickets** — `ticket_id`, `title`, `status` (`open` / `in_progress` / `resolved`), `created_by`, `created_at`
- **ticket_messages** — `message_id`, `ticket_id` (FK &rarr; `tickets.ticket_id`, `ON DELETE CASCADE`), `message_text`, `author`, `created_at`

Both tables are created automatically on startup (`ensure_schema()` in
`app.py`), and three sample tickets with two messages each are seeded the
first time the tables are empty (`seed_if_empty()`), covering all three
statuses.

## Endpoints

- `GET /healthz` — health check
- `GET /tickets?status=open` — list tickets (optional status filter), each with a `message_count`
- `POST /tickets` — create a ticket, body `{"title": ..., "created_by": ...}`
- `GET /tickets/<id>` — one ticket plus all of its messages
- `PATCH /tickets/<id>` — update status, body `{"status": "open" | "in_progress" | "resolved"}`
- `POST /tickets/<id>/messages` — add a message, body `{"message_text": ..., "author": ...}`

## Reusing the existing Lakebase connection

This app intentionally reuses the same Lakebase instance and
`database/lakebase-url` secret scope already set up for the
[databricks-lakebase-app-day-1](https://github.com/modern-data-engineering-lab/databricks-lakebase-app-day-1)
project in this workspace — no new secret setup is needed. `tickets` and
`ticket_messages` just live alongside `watchlist`/`massive_records` as new
tables in the same Postgres database.

## Run locally

Local runs still need Databricks auth so `WorkspaceClient()` can fetch the
Lakebase secret — set `DATABRICKS_HOST` to your workspace URL (via env var,
or persist it in your shell profile) and make sure `databricks auth login`
has been run once.

```bash
pip install -r requirements.txt
export DATABRICKS_HOST="https://<your-workspace>.cloud.databricks.com"
python app.py
```

## Deploy as a Databricks App

1. Create a Git folder in your Databricks workspace pointing at this repo.
2. Compute &rarr; Apps &rarr; Create app &rarr; Custom, and point it at the Git folder.
   Databricks reads `app.yaml` automatically.
3. Deploy, then open the app URL and confirm `/healthz` responds and the
   ticket list loads.

## Notes

- No third-party API calls are made anywhere in this app — everything reads
  and writes Lakebase directly, so the Databricks Free Edition outbound
  network restriction that affected the day-1 watchlist app's Massive API
  calls does not apply here.
- No secrets, passwords, or API keys are stored in this repo — the Lakebase
  connection URL is resolved at runtime from the Databricks secret scope.
