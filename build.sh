#!/usr/bin/env bash
# Render Build Script
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Run Django management commands from the inner project directory
cd finance_ai
python manage.py collectstatic --noinput
python manage.py migrate --noinput
