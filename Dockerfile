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

# Seeding only happens in DEMO_MODE (default on); real deployments set
# DEMO_MODE=false and start from an empty schema instead.
CMD ["sh", "-c", "python -c 'import db,seed; from web import access; (seed.build() if access.demo_mode() else db.init_schema()) if not db.db_exists() else None' && python web_app.py"]
