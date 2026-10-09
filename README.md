# User Management System

An educational FastAPI project implementing registration, JWT login, and authenticated profile updates. Users are stored in SQLite, passwords are hashed with bcrypt, and requests are validated with Pydantic.

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
cp app/.env.example app/.env
```

Generate a signing key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Replace the placeholder in `app/.env` with the generated key:

```dotenv
JWT_SECRET_KEY=your-generated-key
JWT_ALGORITHM=HS256
```

Keep the real signing key private. `.env` and the local database are ignored by Git. The application loads `app/.env` explicitly; existing environment variables take precedence. Changing the signing key invalidates existing tokens.

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

Names are trimmed and must contain 1–50 characters. Emails are checked for valid format and must be unique in the database. Registration and login schemas require passwords of at least 8 characters. bcrypt accepts at most 72 UTF-8 bytes; the hashing helper rejects longer passwords, but registration does not yet translate that failure into a validation response.

Despite using `PUT` as required by the assignment, `/update` applies partial updates. It accepts `first_name`, `last_name`, and `email`; omitted fields remain unchanged. Empty requests, explicit `null`, and unsupported fields are rejected. Password changes are not implemented.

Authentication middleware verifies the Bearer token before allowing updates. The token's user ID determines whose account changes. Missing/invalid tokens or nonexistent users return `401`; duplicate emails return `409`; request validation errors return `422`. A rejected duplicate-email update rolls back every requested change.

Passwords and password hashes are not included in successful API responses.

### Try the flow in Swagger UI

1. Open `/docs` and register a user using **Try it out → Execute**.
2. Log in with that user's credentials and copy the `access_token` value.
3. Click **Authorize** and paste only the token, without the `Bearer` prefix or quotes.
4. Execute `/update` with a body such as `{"first_name": "Updated"}`.

Swagger adds the `Authorization: Bearer <token>` header to the protected request. Logging in alone does not automatically authorize later requests.

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

## Tests

Run from the project root with `.venv` activated. No running Uvicorn server is needed.

Database construction, insertion/readback, and email uniqueness checks:

```bash
python -m tests.check_database
```

Login and update tests:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Only the HTTP update tests:

```bash
python -m unittest discover -s tests -p test_update.py -v
```

Tests use temporary in-memory databases. Login and update tests use test signing keys, leaving `users.db` and the real signing key unchanged. Login tests call the function directly; update tests use `TestClient` to exercise HTTP requests, middleware, validation, and persistence.

## Learning checkpoints and next steps

Implemented: registration, input validation, SQLite persistence, bcrypt hashing, JWT login, authentication middleware, partial profile updates, and database/login/update checks.

Assignment bonuses remain: token expiration, authenticated `GET /profile`, caching with invalidation after updates, and Docker packaging. Current tokens have no expiration. Login also currently uses different error messages for unknown email and incorrect password; a shared invalid-credentials message is a follow-up improvement.
