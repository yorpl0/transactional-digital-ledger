.PHONY: up down test demo stress http-benchmark http-limit lint
up:
	docker compose up --build -d
down:
	docker compose down
test:
	docker compose run --rm api pytest -q
demo:
	docker compose exec -T api python -m app.demo
stress:
	docker compose run --rm api python -m tests.stress
http-benchmark:
	python -m tests.http_benchmark
http-limit:
	python -m tests.http_benchmark --full
lint:
	ruff check .

