from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import cache, database
from app.cache import cache_profile, get_cached_profile
from app.database import SessionLocal
from app.dependencies import get_current_user_id
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, UpdateRequest
from app.security import create_access_token, hash_password, verify_password

app = FastAPI()


@app.get("/health")
def health():
    """
    Report dependency availability without exposing connection details.
    """
    failed = []
    # Check database connection first
    try:
        with database.engine.connect() as connection:
            if connection.execute(text("SELECT 1")).scalar() != 1:
                failed.append("database")
    except SQLAlchemyError:
        failed.append("database")

    # Check Redis even when the database check fails.
    try:
        if not cache.redis_client.ping():
            failed.append("redis")
    except RedisError:
        failed.append("redis")

    if failed:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "failed_dependencies": failed},
        )
    return {"status": "healthy"}


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
        # Use the same response for unknown accounts and incorrect passwords.
        if existing_user is None or not verify_password(
            password=user.password, password_hash=existing_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )
        # else, we issue token for successful log-in
        token = create_access_token(existing_user.id)
        return {"access_token": token, "token_type": "bearer"}


@app.put("/update")
def update(
    changes: UpdateRequest,
    user_id: int = Depends(get_current_user_id),
):
    """
    Updates the profile information of the authenticated user.
    The user must provide at least one field to update (first name, last name, or email).
    """
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
def profile(user_id: int = Depends(get_current_user_id)):
    """
    Returns the profile information of the authenticated user.
    If the profile data is cached in Redis, it will be returned from the cache.
    Otherwise, it will be retrieved from the database and cached for future requests.
    """
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

    uvicorn.run("app.main:app", reload=True)
