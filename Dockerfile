FROM python:3.14-slim

WORKDIR /service

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["sh", "-c", "python app/database.py && python -m uvicorn main:app --app-dir app --host 0.0.0.0 --port 8000"]