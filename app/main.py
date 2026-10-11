from cache import cache_profile, get_cached_profile
from database import SessionLocal
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from models import User
from schemas import LoginRequest, RegisterRequest, UpdateRequest
from security import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

app = FastAPI()
bearer_scheme = HTTPBearer(auto_error=False)


@app.middleware("http")
async def authenticate_update(request: Request, call_next):
    """
    Middleware called by FastAPI whenever an HTTP request arrives.
    Serves to authenticate requests to the /update and /profile endpoint.
    """
    # cheking if the given request needs token verification
    if (request.method == "PUT" and request.url.path == "/update") or (
        request.method == "GET" and request.url.path == "/profile"
    ):
        # extract Authorization
        authorization = request.headers.get("Authorization", "")
        parts = authorization.split()

        # check if the Authorization header is valid
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authentication credentials."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # extract the token and verify it
        token = parts[1]
        try:
            user_id = verify_access_token(token)
        except InvalidTokenError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid authentication credentials."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.user_id = user_id

    # authentication passed - continue to the next middleware or endpoint
    return await call_next(request)


@app.post("/register", status_code=201)
def register(user: RegisterRequest):

    # adding a user entity to the User table
    with SessionLocal() as session:
        db_user = User(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            password_hash=hash_password(user.password),
        )

        session.add(db_user)
        try:
            session.commit()
        except IntegrityError:
            # examine wether the database rejected a duplicate email
            session.rollback()
            existing_user = session.scalar(select(User).where(User.email == user.email))
            if existing_user is not None:
                raise HTTPException(
                    status_code=409, detail="Email is already registered."
                ) from None
            # else, raise the different error
            raise
        # The saving of the addition succeeds
        session.refresh(db_user)

    return {
        "id": db_user.id,
        "first_name": db_user.first_name,
        "last_name": db_user.last_name,
        "email": db_user.email,
    }


@app.post("/login", status_code=200)
def login(user: LoginRequest):

    # Finding user and verify password
    with SessionLocal() as session:
        existing_user = session.scalar(select(User).where(User.email == user.email))
        # If the user does not exists
        if existing_user is None:
            raise HTTPException(status_code=401, detail="Email is not registered.")
        # If the submitted password does not match the stored hash
        elif not verify_password(
            password=user.password, password_hash=existing_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="password is inccorrect for the registered user.",
            )
        # else, we issue token for successful log-in
        token = create_access_token(existing_user.id)
        return {"access_token": token, "token_type": "bearer"}


@app.put("/update")
def update(
    changes: UpdateRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    """
    Updates the profile information of the authenticated user.
    The user must provide at least one field to update (first name, last name, or email).
    """
    user_id = request.state.user_id

    with SessionLocal() as session:
        db_user = session.get(User, user_id)

        # If the user does not exist in the database
        if db_user is None:
            raise HTTPException(
                status_code=401,
                detail="User no longer exists.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # converts a Pydantic model to a dictionary
        supplied_changes = changes.model_dump(exclude_unset=True)

        # apply the changes to the user object in the database
        for field, value in supplied_changes.items():
            setattr(db_user, field, value)

        # try commit the changes to the database
        try:
            session.commit()
        except IntegrityError:
            # examine wether the database rejected a duplicate email
            session.rollback()
            if "email" in supplied_changes:
                existing_user = session.scalar(
                    select(User).where(
                        User.email == supplied_changes["email"],
                        User.id != user_id,
                    )
                )
                if existing_user is not None:
                    raise HTTPException(
                        status_code=409, detail="Email is already registered."
                    ) from None
            raise
        session.refresh(db_user)

        profile_data = {
            "id": db_user.id,
            "first_name": db_user.first_name,
            "last_name": db_user.last_name,
            "email": db_user.email,
        }

        # cache the updated profile data in Redis for future requests
        cache_profile(profile_data)

        return profile_data


@app.get("/profile")
def profile(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    """
    Returns the profile information of the authenticated user.
    If the profile data is cached in Redis, it will be returned from the cache.
    Otherwise, it will be retrieved from the database and cached for future requests.
    """
    user_id = request.state.user_id

    # try to retrieve the cached profile data from Redis
    cached_profile = get_cached_profile(user_id)

    # if the cached profile data is found and valid, return it
    if cached_profile is not None:
        return cached_profile.model_dump(mode="json")

    # Else, retrieve the profile data from the database and cache it
    with SessionLocal() as session:
        # find the user in the database
        db_user = session.get(User, user_id)

        # if the user does not exist in the database
        if db_user is None:
            raise HTTPException(
                status_code=401,
                detail="User no longer exists.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        profile_data = {
            "id": db_user.id,
            "first_name": db_user.first_name,
            "last_name": db_user.last_name,
            "email": db_user.email,
        }

        # cache the profile data in Redis for future requests
        cache_profile(profile_data)
        return profile_data


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", reload=True)
