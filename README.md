# User Management System

FastAPI service for user registration, JWT authentication, and profile management, with PostgreSQL persistence and Redis caching.

## Features

- **Registration:** validated input, unique emails, and bcrypt password hashing.
- **Authentication:** signed JWT access tokens with configurable expiration (15 minutes by default).
- **Profile management:** authenticated retrieval and partial updates.
- **Redis caching:** profile caching with TTL, refresh after updates, and database fallback.
- **Database:** PostgreSQL 17 with Alembic schema migrations.
- **Health checks:** public database and Redis availability checks.
- **Docker Compose:** API, PostgreSQL, and Redis services with persistent database storage.
- **Configuration:** centralized, validated settings using pydantic-settings.
- **Testing:** automated configuration, database, login, update, expiration, and cache checks.

## Setup and run

For local development, use Python 3.14 and PostgreSQL; Redis is needed for caching and a healthy health response. Docker Compose provides the database and the containerized application stack. Run commands from the project root.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Skip environment creation or template copying if those files already exist. Set `JWT_SECRET_KEY` to the generated value and configure the root `.env` using **unquoted values**:

```dotenv
JWT_SECRET_KEY=your-generated-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=15
POSTGRES_PASSWORD=your-generated-database-password
DATABASE_URL=postgresql+psycopg://app:your-generated-database-password@127.0.0.1:5432/app
TEST_DATABASE_URL=postgresql+psycopg://app:your-generated-database-password@127.0.0.1:5432/app_test
REDIS_URL=redis://127.0.0.1:6379/0
PROFILE_CACHE_TTL_SECONDS=120
```

`Settings` in `app/core/config.py` loads the root `.env`; environment variables take precedence. `JWT_SECRET_KEY` and `DATABASE_URL` are required and cannot be empty. Missing or invalid settings stop startup with a validation error naming the field. Token and cache lifetimes must be positive integers.

Generate a database password with `python -c "import secrets; print(secrets.token_hex(24))"` and use the same value in `POSTGRES_PASSWORD` and both database URLs. Start PostgreSQL with `docker compose up -d db`. Database credentials initialize new volumes only; changing `.env` does not change an existing PostgreSQL user's password.

For local execution, install Redis (`brew install redis` on macOS) and start it in a separate terminal:

```bash
redis-server --bind 127.0.0.1 --port 6379
```

Apply migrations and start the local API:

```bash
python -m alembic upgrade head
python -m app.main
```

After changing a database model, generate a migration with `python -m alembic revision --autogenerate -m "Describe the change"`, review its upgrade/downgrade operations, and apply it with `python -m alembic upgrade head`. Alembic owns the schema; `database.py` only provides the engine and sessions.

Open [Swagger UI](http://127.0.0.1:8000/docs).

## API Endpoints

| Endpoint | Authentication | Successful response |
| --- | --- | --- |
| `POST /register` | None | `201`, public user details |
| `POST /login` | Email and password | `200`, access token |
| `PUT /update` | Bearer token | `200`, updated public details |
| `GET /profile` | Bearer token | `200`, public profile |
| `GET /health` | None | `200` when PostgreSQL and Redis respond; otherwise `503` |

**Notes:**

* Names are trimmed and limited to 1–50 characters.
* Emails are validated and unique.
* Passwords require at least 8 characters.
* Updates accept selected profile fields; omitted fields remain unchanged.
* Invalid input, empty updates, explicit `null`, and unsupported update fields return `422`. Invalid authentication returns `401`; duplicate emails return `409`.
* Passwords and hashes are excluded from public responses.
* Health failures name only the unavailable dependencies, without connection details.

## Request Examples

**Register and log in:**

```bash
curl -i -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Avital","last_name":"Example","email":"avital@example.com","password":"learning123"}'

curl -i -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"avital@example.com","password":"learning123"}'
```

**Update and retrieve the profile:** replace `PASTE_YOUR_TOKEN_HERE` with the login response's `access_token`.

```bash
curl -i -X PUT http://127.0.0.1:8000/update \
  -H 'Authorization: Bearer PASTE_YOUR_TOKEN_HERE' \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Updated"}'

curl -i http://127.0.0.1:8000/profile \
  -H 'Authorization: Bearer PASTE_YOUR_TOKEN_HERE'
```

In Swagger, log in, copy the token, and enter it through **Authorize** without quotes or the `Bearer` prefix. Expired tokens require another login.

## Docker Compose

With Docker running, port 8000 available, and the root `.env` configured, start the services:

```bash
docker compose up --build
```

Compose starts `app`, `db`, and `redis`. PostgreSQL uses `pgvector/pgvector:pg17`. The API connects to `db:5432/app` and `redis:6379/0`, waits for both health checks, and runs `alembic upgrade head` before starting. No host PostgreSQL or Redis installation is required.

The API is available at [Swagger UI](http://127.0.0.1:8000/docs), with readiness at [Health](http://127.0.0.1:8000/health). PostgreSQL persists in the named `postgres-data` volume and is published locally on port 5432. Redis cache data is disposable; Redis is accessible only within the Compose network.

Stop and remove the service containers:

```bash
docker compose down
```

This removes the containers but preserves database data. Avoid `docker compose down -v` unless you intend to delete the volumes.

## Tests

Run with the local virtual environment activated and PostgreSQL running; no API or Redis server is needed. Create the separate test database once (skip if it exists):

```bash
docker compose up -d db
docker compose exec db psql -U app -d postgres -c "CREATE DATABASE app_test;"
```

Configure `TEST_DATABASE_URL` for `app_test`, then prepare and run the tests:

```bash
python -m tests.setup_database
python -m tests.check_database
python -m unittest discover -s tests -p 'test_*.py' -v
```

Database-backed tests apply Alembic migrations to PostgreSQL `app_test` and reset its user records between tests. Guards reject other database names. Redis stays fake or mocked; JWT tests use test keys. Configuration tests isolate environment values and cover required settings, positive durations, and secret-safe errors. The full suite includes the original database checks.
