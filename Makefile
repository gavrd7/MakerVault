SHELL := /bin/bash

.PHONY: up pull down logs build up-build rebuild-app update shell migrate seed-catalogue enrich-board-catalogue seed-catalogue-images cache-catalogue-images refresh-catalogue createsuperuser check

up:
	docker compose up -d

pull:
	docker compose pull

down:
	docker compose down

logs:
	docker compose logs -f makervault

build:
	docker compose -f compose.yaml -f compose.build.yaml build --pull

up-build:
	docker compose -f compose.yaml -f compose.build.yaml up -d --build

rebuild-app:
	docker compose -f compose.yaml -f compose.build.yaml up -d --build --no-deps makervault

update:
	git pull --ff-only
	docker compose pull
	docker compose up -d

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
