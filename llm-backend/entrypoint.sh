#!/bin/bash
set -e

echo "Starting application..."
echo "Note: Database migrations should be run manually before first deployment"
echo "Run: python db.py --migrate && python db.py --seed-guidelines data/seed_guidelines.json"

exec uvicorn main:app --host 0.0.0.0 --port 8000
