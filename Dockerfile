FROM python:3.14-slim

WORKDIR /service

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
# copy Alembic’s configuration and migration files into the image
COPY alembic.ini .
COPY migrations/ ./migrations/

EXPOSE 8000

# Apply DB migrations → if successful, start the API
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]