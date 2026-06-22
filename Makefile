# Makefile for Motionmate Django Project

.PHONY: help install migrate runserver test lint format clean

# Default target
help:
	@echo "Available targets:"
	@echo "  install    - Install dependencies"
	@echo "  migrate    - Run database migrations"
	@echo "  runserver  - Start the Django development server"
	@echo "  test       - Run tests"
	@echo "  lint       - Run linter (ruff)"
	@echo "  format     - Format code (black)"
	@echo "  clean      - Clean up Python cache files"
	@echo "  help       - Show this help message"

# Install dependencies
install:
	uv sync --extra dev

# Run database migrations
migrate:
	uv run --no-sync python src/manage.py migrate

# Start the development server
runserver:
	uv run --no-sync python src/manage.py runserver

# Run tests
test:
	uv run --no-sync python src/manage.py test apps.crm.tests apps.accounts.tests apps.businesses.tests apps.billings.tests

# Run linter
lint:
	uv run --no-sync ruff check .

# Format code
format:
	uv run --no-sync black .

# Clean up cache files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
