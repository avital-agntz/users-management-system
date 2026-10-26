# Local backend baseline

Assignment Section 1.1: start the backend and run the existing tests.

- Date: 2026-10-21 (Asia/Jerusalem).
- Branch: `aws-deployment`.
- Application commit: `6922b3d` (Stage 1A foundation).
- Local test interpreter: Python 3.14.8.
- Services: FastAPI, PostgreSQL 17, and Redis 7 via Docker Compose.

## Database isolation

The existing `postgres-data` volume contained Stage 1B Alembic revision
`a14c9b27f603`. Initial API startup failed because Stage 1A only knows revision
`e87b5688d943`. No downgrade or deletion was performed.

Added `docker-compose.aws-local.yml` to select a separate persistent volume,
`users-management-aws-deployment-postgres-data`. Started the stack with:

```bash
docker compose -f docker-compose.yml -f docker-compose.aws-local.yml up -d --build
```

Created the dedicated `app_test` database in that volume, then ran:

```bash
.venv/bin/python -m tests.setup_database
.venv/bin/python -m tests.check_database
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

## Results

- Test migrations: passed.
- Database checks: passed.
- Existing automated suite: **43 tests passed**, no failures or errors.
- `GET http://127.0.0.1:8000/health`: HTTP 200, `{"status":"healthy"}`.
- `GET http://127.0.0.1:8000/docs`: HTTP 200.
- Services left running for the next local frontend step.

The local test run emitted a Starlette TestClient deprecation warning about
httpx; it did not fail the suite. Dependencies are currently unpinned, so future
image builds may resolve different package versions.

This verifies the existing backend baseline only. Frontend, browser journeys,
AWS deployment, monitoring, concurrency, and fault experiments remain pending.
