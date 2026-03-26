#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_catalog
python manage.py bootstrap_admin
python manage.py collectstatic --noinput
