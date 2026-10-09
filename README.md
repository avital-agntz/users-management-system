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
JWT_EXPIRE_MINUTES=15
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

* Names are trimmed and must contain 1–50 characters. 
* Emails are checked for valid format and must be unique in the database. 
* Registration and login schemas require passwords of at least 8 characters. 


### Try the flow in Swagger UI

1. Open `/docs` and register a user using **Try it out → Execute**.
2. Log in with that user's credentials and copy the `access_token` value.
3. Click **Authorize** and paste only the token, without the `Bearer` prefix or quotes.
4. Execute `/update` with a body such as `{"first_name": "Updated"}`.


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

Tokens expire after 15 minutes, configured by `JWT_EXPIRE_MINUTES` in `app/.env`. Expired tokens return `401`; log in again to obtain a new token. Verification requires an expiration claim, so older tokens without `exp` are also rejected.

Run the expiration tests from the project root with `.venv` activated:

```bash
python -m unittest discover -s tests -p test_token_expiration.py -v
```
