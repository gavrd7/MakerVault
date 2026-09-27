SHELL := /bin/bash

.PHONY: up down logs build rebuild-app update shell migrate seed-catalogue enrich-board-catalogue seed-catalogue-images cache-catalogue-images refresh-catalogue createsuperuser check

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

enrich-board-catalogue:
	docker compose exec makervault python manage.py enrich_board_catalogue

seed-catalogue-images:
	docker compose exec makervault python manage.py seed_catalogue_images --force-retry

cache-catalogue-images:
	docker compose exec makervault python manage.py cache_catalogue_images

refresh-catalogue:
	docker compose exec makervault python manage.py seed_catalogue
	docker compose exec makervault python manage.py enrich_board_catalogue
	docker compose exec makervault python manage.py seed_catalogue_images --force-retry

createsuperuser:
	docker compose exec makervault python manage.py createsuperuser

check:
	docker compose exec makervault python manage.py check --deploy
