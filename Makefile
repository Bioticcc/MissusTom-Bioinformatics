.PHONY: backend-install frontend-install backend-dev frontend-dev check

backend-install:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -e 'backend[dev]'

frontend-install:
	cd desktop && npm install

backend-dev:
	./scripts/dev-backend.sh

frontend-dev:
	./scripts/dev-frontend.sh

check:
	./scripts/check.sh

