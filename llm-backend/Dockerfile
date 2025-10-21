FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create db directory
RUN mkdir -p db

# Initialize database on startup
CMD ["sh", "-c", "python db.py --migrate && python db.py --seed data/seed_contents.json && uvicorn main:app --host 0.0.0.0 --port 8000"]
