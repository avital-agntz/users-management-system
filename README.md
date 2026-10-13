# User Management System

FastAPI service for user registration, JWT authentication, and profile management, with SQLite persistence and Redis caching.

## Features

- **Registration:** validated input, unique emails, and bcrypt password hashing.
- **Authentication:** signed JWT access tokens with configurable expiration (15 minutes by default).
- **Profile management:** authenticated retrieval and partial updates.
- **Redis caching:** profile caching with TTL, refresh after updates, and database fallback.
- **Docker Compose:** API and Redis containers with persistent SQLite storage.
- **Configuration:** centralized, validated settings using pydantic-settings.
- **Testing:** automated configuration, database, login, update, expiration, and cache checks.

## Setup and run

For local development, use Python 3.14 and Redis. For container execution, use Docker with Compose. Run commands from the project root.

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
DATABASE_URL=sqlite:///./users.db
REDIS_URL=redis://127.0.0.1:6379/0
PROFILE_CACHE_TTL_SECONDS=120
```

`Settings` in `app/core/config.py` loads the root `.env`; environment variables take precedence. `JWT_SECRET_KEY` and `DATABASE_URL` are required and cannot be empty. Missing or invalid settings stop startup with a validation error naming the field. Token and cache lifetimes must be positive integers.

For local execution, install Redis (`brew install redis` on macOS) and start it in a separate terminal:

```bash
redis-server --bind 127.0.0.1 --port 6379
```

Create the tables and start the API:

```bash
python -m app.database
python -m app.main
```

Open [Swagger UI](http://127.0.0.1:8000/docs).

## API Endpoints

| Endpoint | Authentication | Successful response |
| --- | --- | --- |
| `POST /register` | None | `201`, public user details |
| `POST /login` | Email and password | `200`, access token |
| `PUT /update` | Bearer token | `200`, updated public details |
| `GET /profile` | Bearer token | `200`, public profile |

**Notes:**

* Names are trimmed and limited to 1–50 characters.
* Emails are validated and unique.
* Passwords require at least 8 characters.
* Updates accept selected profile fields; omitted fields remain unchanged.
* Invalid input, empty updates, explicit `null`, and unsupported update fields return `422`. Invalid authentication returns `401`; duplicate emails return `409`.
* Passwords and hashes are excluded from public responses.

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

Compose builds the API image and starts two services: `app` and `redis`. It overrides the database URL to `sqlite:////data/users.db` and the Redis URL to `redis://redis:6379/0`. The API initializes missing tables after Redis passes its health check. No host Redis installation is required.

The API is available at [Swagger UI](http://127.0.0.1:8000/docs). SQLite persists in the named `users-management-data` volume. Redis cache data is disposable; Redis is accessible only within the Compose network.

Stop and remove the service containers:

```bash
docker compose down
```

This removes the containers but preserves SQLite data. Avoid `docker compose down -v` unless you intend to delete the database volume.

## Tests

Run with the local virtual environment activated; no API server is needed.

```bash
python -m tests.check_database
python -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use explicit test settings, temporary SQLite databases, and fake or mocked Redis; no running Redis server or real `.env` is required. Configuration tests cover required values, duration validation, and secret-safe error messages.
