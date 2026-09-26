SHELL := /bin/bash

.PHONY: up down logs build rebuild-app update shell migrate seed-catalogue cache-catalogue-images createsuperuser check

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f makervault

build:
	docker compose build --pull

rebuild-app:
	docker compose up -d --build --no-deps makervault

update:
	git pull --ff-only
	docker compose up -d --build --no-deps makervault

shell:
	docker compose exec makervault python manage.py shell

migrate:
	docker compose exec makervault python manage.py migrate

seed-catalogue:
	docker compose exec makervault python manage.py seed_catalogue

cache-catalogue-images:
	docker compose exec makervault python manage.py cache_catalogue_images

createsuperuser:
	docker compose exec makervault python manage.py createsuperuser

check:
	docker compose exec makervault python manage.py check --deploy
