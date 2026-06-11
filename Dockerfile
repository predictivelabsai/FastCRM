FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Database lives on a mounted volume so it survives image rebuilds.
ENV FASTCRM_DB=/data/fastcrm.sqlite
ENV FASTCRM_PORT=5006
EXPOSE 5006

# Seed on first boot if the DB is missing, then serve.
CMD ["sh", "-c", "python -c 'import db,seed; seed.build() if not db.db_exists() else None' && python web_app.py"]
