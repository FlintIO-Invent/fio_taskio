# Makefile for TaskIO Django Project

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
	pip install -e .[dev]

# Run database migrations
migrate:
	cd src && /home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/.venv/bin/python manage.py migrate

# Start the development server
runserver:
	cd src && /home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/.venv/bin/python manage.py runserver

# Run tests
test:
	cd src && /home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/.venv/bin/python manage.py test

# Run linter
lint:
	ruff check .

# Format code
format:
	black .

# Clean up cache files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +