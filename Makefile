# Atajos de desarrollo. En Windows sin `make`, ver los equivalentes de PowerShell
# en la sección 5 del README.

.PHONY: up down logs migrate test lint format

up:        ## Construye y levanta API + Postgres en segundo plano
	docker compose up -d --build

down:      ## Detiene los servicios (conserva el volumen de datos)
	docker compose down

logs:      ## Sigue los logs de todos los servicios
	docker compose logs -f

migrate:   ## Aplica las migraciones de Alembic dentro del contenedor de la API
	docker compose exec api alembic upgrade head

test:      ## Corre pytest en el venv local (requiere la base arriba y migrada)
	pytest

lint:      ## Revisa estilo y formato con ruff
	ruff check .
	ruff format --check .

format:    ## Corrige lo que ruff pueda arreglar solo
	ruff check --fix .
	ruff format .
