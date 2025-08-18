all: clean install test

install:
	poetry install --with dev --all-extras

lint:
	poetry run flake8 openaleph_search --count --select=E9,F63,F7,F82 --show-source --statistics
	poetry run flake8 openaleph_search --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

pre-commit:
	poetry run pre-commit install
	poetry run pre-commit run -a

typecheck:
	poetry run mypy --strict openaleph_search

test:
	poetry run pytest -v --capture=sys --cov=openaleph_search --cov-report lcov

build:
	poetry run build

clean:
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

documentation:
	mkdocs build
	aws --endpoint-url https://s3.investigativedata.org s3 sync ./site s3://openaleph.org/docs/lib/openaleph-search
