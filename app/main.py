from database import SessionLocal
from fastapi import FastAPI, HTTPException
from models import User
from schemas import LoginRequest, RegisterRequest
from security import create_access_token, hash_password, verify_password
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

app = FastAPI()


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


@app.get("/profile")
def profile():
    return {"status": "ok"}


@app.put("/update")
def update():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", reload=True)
