.PHONY: setup lint format typecheck test pipeline audit-hipaa docker-up docker-qa clean

setup:
	uv sync --dev
	uv run lefthook install

lint:
	uv run --no-sync ruff check src tests scripts
	uv run --no-sync ruff format --check src tests scripts

format:
	uv run --no-sync ruff format src tests scripts

typecheck:
	uv run --no-sync mypy src tests scripts

test:
	uv run --no-sync pytest --cov=src/healthcare_lakehouse --cov=scripts --cov-branch --cov-report=term-missing --cov-fail-under=100

pipeline:
	uv run --no-sync healthcare-lakehouse run-pipeline --patients 12 --seed 42 --output-dir data/local_run --verify-hipaa

audit-hipaa:
	uv run --no-sync python scripts/git_hooks.py block-phi
	uv run --no-sync healthcare-lakehouse run-pipeline --patients 12 --seed 42 --output-dir data/audit_run --verify-hipaa

docker-up:
	docker compose -f compose.yaml up --build --abort-on-container-exit

docker-qa:
	docker compose -f compose.yaml --profile qa run --rm lakehouse-qa

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov data/local_run data/audit_run
