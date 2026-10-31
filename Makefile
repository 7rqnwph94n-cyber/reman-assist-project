PYTHON ?= python3
PYTHON_E2E ?= python3.12

.PHONY: venv venv-e2e venv-load test e2e load seed

venv:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate; python -m pip install -r requirements.txt; python -m pip install -r requirements-test.txt

venv-e2e:
	$(PYTHON_E2E) -m venv .venv-e2e
	. .venv-e2e/bin/activate; python -m pip install -r requirements.txt; python -m pip install -r requirements-test.txt; python -m pip install -r requirements-e2e.txt; python -m playwright install

venv-load:
	$(PYTHON) -m venv .venv-load
	. .venv-load/bin/activate; python -m pip install -r requirements.txt; python -m pip install -r requirements-load.txt

test:
	. .venv/bin/activate; python -m pytest

e2e:
	. .venv-e2e/bin/activate; python -m pytest e2e

load:
	. .venv-load/bin/activate; locust -f load/locustfile.py --host http://127.0.0.1:5001

seed:
	FLASK_CONFIG=testing APP_ENV=dev ALLOW_DANGEROUS_COMMANDS=1 flask seed --reset --templates 2 --jobs 10 --items-per-template 20 --bom-lines-per-job 30
