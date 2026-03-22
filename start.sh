#!/bin/bash
# Start WDK Node.js service in background, then FastAPI in foreground
(cd /app/wdk-service && node index.js) &
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
