#!/bin/bash
set -e

echo "🔄 Running database migrations via Alembic..."
alembic upgrade head
echo "✅ Database schema is up-to-date."

echo "🚀 Executing Ingestion Task..."
exec "$@"