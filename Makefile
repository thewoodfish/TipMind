.PHONY: install dev backend frontend migrate lint

install:
	pip install -r requirements.txt
	cd frontend && npm install

dev:
	$(MAKE) -j2 backend frontend

backend:
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

migrate:
	python -c "import asyncio; from backend.data.database import create_all_tables; asyncio.run(create_all_tables())"

lint:
	ruff check backend/
	cd frontend && npm run lint

test:
	pytest backend/tests/ -v
