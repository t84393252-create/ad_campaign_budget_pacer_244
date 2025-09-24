.PHONY: help build run test clean docker-up docker-down load-test

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*##"; printf "\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-15s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

build: ## Build all services
	cd pacer-service && go build -o pacer-service .
	cd api && pip install -r requirements.txt

run-pacer: ## Run the Go pacing service
	cd pacer-service && go run .

run-api: ## Run the Python API service
	cd api && uvicorn main:app --reload --host 0.0.0.0 --port 8000

test: ## Run all tests
	cd pacer-service && go test ./... -v
	cd api && pytest -v

clean: ## Clean build artifacts
	cd pacer-service && go clean
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker-up: ## Start all services with Docker Compose
	docker-compose up -d

docker-down: ## Stop all Docker services
	docker-compose down

docker-build: ## Build Docker images
	docker-compose build

docker-logs: ## View Docker logs
	docker-compose logs -f

load-test: ## Run load testing
	python scripts/load-test.py

init-db: ## Initialize database
	docker-compose exec postgres psql -U postgres -d budget_pacer -f /docker-entrypoint-initdb.d/init.sql

monitor: ## Open monitoring dashboards
	@echo "Opening Grafana at http://localhost:3000"
	@echo "Prometheus at http://localhost:9090"