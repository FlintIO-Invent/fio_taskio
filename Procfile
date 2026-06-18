release: python src/manage.py migrate
web: gunicorn taskio.wsgi:application --chdir src --log-file - --bind 0.0.0.0:${PORT:-8000}
