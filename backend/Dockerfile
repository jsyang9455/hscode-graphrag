FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY orchestration /app/orchestration
COPY data/kcs/chapter_ko.json /app/data/kcs/chapter_ko.json
COPY data/kcs/harmonized_system.csv /app/data/kcs/harmonized_system.csv
COPY data/kcs/kcs_hsk_priority.csv /app/data/kcs/kcs_hsk_priority.csv
COPY scripts /app/scripts

ENV PYTHONPATH=/app
ENV DATABASE_URL=postgresql+psycopg2://hscode:hscode@db:5432/hscode_graphrag

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
