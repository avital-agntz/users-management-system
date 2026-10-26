FROM python:3.14-slim

WORKDIR /service

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
# copy Alembic’s configuration and migration files into the image
COPY alembic.ini .
COPY migrations/ ./migrations/
# AWS certificate bundle, so the app can verify it is talking to the real RDS server
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /service/certs/global-bundle.pem

EXPOSE 8000

# Start the API only; migrations run separately (the `migrate` service in docker-compose.yml)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]