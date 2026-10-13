"""
Check the user model against the migrated PostgreSQL app_test database.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from tests.database_fixture import isolated_database


def test_db_construction():
    """
    Tests the database construction with its tables.
    """
    with isolated_database() as engine:

        # opening a session with the engine
        with Session(engine) as session:
            # Query that selects all the users
            users = session.scalars(select(User)).all()
            assert users == [], "A new database should contain no users."
            print("Users:", users)
            print("Database check passed: the users table exists and is empty.")


def test_db_add_read():
    """
    Tests adding and reading users from User table.
    """
    with isolated_database() as engine:

        # opening a session with the engine
        with Session(engine) as session:
            user = User(
                first_name="Avital",
                last_name="Example",
                email="avital@example.com",
                password_hash="test-placeholder-not-a-real-hash",
            )
            session.add(user)
            session.commit()

            saved_user = session.scalar(
                select(User).where(User.email == "avital@example.com")
            )

            assert saved_user is not None
            assert saved_user.id is not None
            assert saved_user.first_name == "Avital"

            print("Edit users check passed: the users table exists and is not empty.")


def test_duplicate_email():
    """
    Tests uniqueness of each email.
    """
    with isolated_database() as engine:

        with Session(engine) as session:
            first_user = User(
                first_name="Avital",
                last_name="Example",
                email="same@example.com",
                password_hash="test-placeholder",
            )
            session.add(first_user)
            session.commit()

            second_user = User(
                first_name="Another",
                last_name="User",
                email="same@example.com",
                password_hash="test-placeholder",
            )
            session.add(second_user)

            # Trying to add another user with the same email
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
            else:
                raise AssertionError("Duplicate email should be rejected.")

            users = session.scalars(select(User)).all()
            assert len(users) == 1
            assert users[0].first_name == "Avital"
            print("Duplicate email check passed.")


if __name__ == "__main__":
    test_db_construction()
    test_db_add_read()
    test_duplicate_email()
