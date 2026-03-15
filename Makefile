.PHONY: install dev backend frontend wdk demo seed test clean lint

PYTHON := python3
NPM    := npm
NODE   := node

# ─────────────────────────────────────────────
# Install all dependencies
# ─────────────────────────────────────────────
install:
	pip install -r requirements.txt
	cd frontend && $(NPM) install
	cd wdk-service && $(NPM) install

# ─────────────────────────────────────────────
# Run all 3 services concurrently (Ctrl-C stops all)
#   :8000 — FastAPI backend
#   :3000 — Next.js frontend
#   :3001 — WDK Node.js microservice
# ─────────────────────────────────────────────
dev:
	@echo "▶  Starting TipMind (FastAPI :8000 + Next.js :3000 + WDK :3001)..."
	@trap 'kill 0' SIGINT; \
		cd wdk-service && $(NODE) index.js & \
		$(PYTHON) -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload & \
		cd frontend && $(NPM) run dev & \
		wait

backend:
	$(PYTHON) -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && $(NPM) run dev

wdk:
	cd wdk-service && $(NODE) index.js

# ─────────────────────────────────────────────
# Seed demo data into the database
# ─────────────────────────────────────────────
seed:
	$(PYTHON) -m backend.demo.seed

# ─────────────────────────────────────────────
# Full demo: seed + start all 3 services + open browser
# ─────────────────────────────────────────────
demo:
	@echo "▶  Seeding demo data..."
	$(PYTHON) -m backend.demo.seed
	@echo "▶  Launching TipMind (FastAPI :8000 + Next.js :3000 + WDK :3001)..."
	@trap 'kill 0' SIGINT; \
		cd wdk-service && $(NODE) index.js & \
		$(PYTHON) -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 & \
		cd frontend && $(NPM) run dev & \
		sleep 5 && open http://localhost:3000 & \
		wait

# ─────────────────────────────────────────────
# Run tests
# ─────────────────────────────────────────────
test:
	pytest backend/ -v --tb=short

# ─────────────────────────────────────────────
# Lint
# ─────────────────────────────────────────────
lint:
	ruff check backend/
	cd frontend && $(NPM) run lint

# ─────────────────────────────────────────────
# Remove build artifacts and database
# ─────────────────────────────────────────────
clean:
	rm -f tipmind.db
	rm -rf frontend/.next
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
