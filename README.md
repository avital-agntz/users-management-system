# User Management System

`FastAPI` project implementing registration, `JWT` login, and authenticated profile updates. Users are stored in `SQLite`, passwords are hashed with `bcrypt`, and requests are validated with `Pydantic`.

## Setup

Developed and tested with Python 3.14. Run the following commands from the project root. These activation commands are for macOS/Linux.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `.venv` already exists, skip its creation and activate it.

Copy the configuration template:

```bash
cp .env.example .env
```

Generate a signing key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Replace the placeholder in the root `.env` with the generated key. If `.env` already exists, keep it rather than overwriting your settings:

```dotenv
JWT_SECRET_KEY=your-generated-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=15
REDIS_URL=redis://127.0.0.1:6379/0
PROFILE_CACHE_TTL_SECONDS=120
```

Keep the real signing key private. `.env` and the local database are ignored by Git. Both security and cache configuration load the root `.env` explicitly; existing environment variables take precedence. Changing the signing key invalidates existing tokens.

Create the database tables:

```bash
python app/database.py
```

This creates `users.db` in the current directory. Run from the project root so setup and the server use the same database file. Re-running this command creates missing tables; it does not migrate existing table definitions.

## Run locally

With the virtual environment activated:

```bash
python app/main.py
```

The development server uses automatic reload and listens at `http://127.0.0.1:8000`. Open the interactive API documentation at `http://127.0.0.1:8000/docs`. Stop the server with **Ctrl + C**; saved users remain in the database.

The root path `/` has no endpoint and returns `404`.

## API behavior

| Endpoint | Purpose | Success |
| --- | --- | --- |
| `POST /register` | Register names, email, and password | `201`, public user details |
| `POST /login` | Verify email/password and issue a JWT | `200`, access token |
| `PUT /update` | Update selected fields of the authenticated user | `200`, public user details |
| `GET /profile` | Read the authenticated user's public details, with Redis caching | `200`, public user details |

* Names are trimmed and must contain 1–50 characters.
* Emails are checked for valid format and must be unique in the database.
* Registration and login schemas require passwords of at least 8 characters.


### Try the flow in Swagger UI

1. Open `/docs` and register a user using **Try it out → Execute**.
2. Log in with that user's credentials and copy the `access_token` value.
3. Click **Authorize** and paste only the token, without the `Bearer` prefix or quotes.
4. Execute `/update` with a body such as `{"first_name": "Updated"}`.
5. Execute `GET /profile` without a request body to read your saved details.


### Example requests with curl

Register a new user:

```bash
curl -i -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Avital","last_name":"Example","email":"avital@example.com","password":"learning123"}'
```

Log in:

```bash
curl -i -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"avital@example.com","password":"learning123"}'
```

Copy the returned token into the following placeholder:

```bash
curl -i -X PUT http://127.0.0.1:8000/update \
  -H 'Authorization: Bearer PASTE_YOUR_TOKEN_HERE' \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Updated"}'
```

Reusing the registration email returns `409`. An update without its Authorization header returns `401`.

### Token expiration

Tokens expire after 15 minutes, configured by `JWT_EXPIRE_MINUTES` in the root `.env`. Expired tokens return `401`; log in again to obtain a new token. Verification requires an expiration claim, so older tokens without `exp` are also rejected.

Run the expiration tests from the project root with `.venv` activated:

```bash
python -m unittest discover -s tests -p test_token_expiration.py -v
```

### Redis profile caching

SQLite stores users permanently. Redis is a separate server holding temporary public profile copies; the Python `redis` dependency connects the application to that server.

On macOS, install Redis once:

```bash
brew install redis
```

Start it in a separate terminal and leave that terminal running:

```bash
redis-server --bind 127.0.0.1 --port 6379
```

In another terminal, `redis-cli ping` should return `PONG`. Stop the foreground Redis server with **Ctrl + C**.

After token verification, `/profile` checks Redis first. A valid cache hit avoids a SQLite query. A miss, invalid cached profile, or Redis read failure falls back to SQLite and attempts to cache the result. Cached data is validated against `UserResponse`, including matching the authenticated user ID, and contains no passwords or hashes.

Entries expire after `PROFILE_CACHE_TTL_SECONDS` (120 seconds by default). Successful updates overwrite the cached profile and reset its lifetime. Failed database updates do not refresh the cache. If a cache write fails, the application attempts to delete the old entry; if both operations fail, stale data may remain until expiration. Redis failures do not undo successful database updates. Direct database edits and concurrent reads/updates can also produce temporarily stale cached data.

Read the profile using curl:

```bash
curl -i http://127.0.0.1:8000/profile \
  -H 'Authorization: Bearer PASTE_YOUR_TOKEN_HERE'
```

Inspect its cache entry, replacing `3` with your user ID:

```bash
redis-cli GET users-management:profile:3
redis-cli TTL users-management:profile:3
```

To demonstrate a cache miss, delete only that cached copy and call `/profile` again:

```bash
redis-cli DEL users-management:profile:3
```

This does not delete the SQLite user. The next profile request recreates the cache entry.

Run the cache tests without a Redis server:

```bash
python -m unittest discover -s tests -p test_cache.py -v
```

They use fake Redis, simulated expiration/failures, and temporary SQLite. Run the database checks with `python -m tests.check_database`. Login, update, and expiration tests are in their corresponding `tests/test_*.py` modules; the update tests currently use the application's cache client unless it is replaced by the test runner.

The remaining assignment bonus is Docker packaging, which will be implemented separately.
