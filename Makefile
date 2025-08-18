PY=python3
VENV=.venv
ACT=. $(VENV)/bin/activate;

.PHONY: venv install install-all install-backend run-mcp run-backend run-ui dev clean

venv:
	$(PY) -m venv $(VENV)
	@echo "Created venv in $(VENV). Activate with: source $(VENV)/bin/activate"

install: venv
	$(ACT) pip install --upgrade pip
	$(ACT) pip install -r requirements.txt

luxriot-status:
	$(ACT) python -c "from app import _luxriot_ensure_index; idx=_luxriot_ensure_index(); print('ready:', bool(idx)); print('files:', getattr(idx,'files',None)); print('chunks:', len(getattr(idx,'chunks',[]) or []))"

install-backend: venv
	$(ACT) pip install --upgrade pip
	$(ACT) pip install -r backend/requirements.txt

install-all: venv
	$(ACT) pip install --upgrade pip
	$(ACT) pip install -r requirements-all.txt

run-mcp:
	$(ACT) FLASK_ENV=development $(PY) app.py

run-backend:
	$(ACT) uvicorn backend.main:app --reload --port 7000

run-ui:
	cd ui && npm run dev

dev:
	@echo "Open three terminals:\n1) make run-mcp\n2) make run-backend\n3) make run-ui"

clean:
	rm -rf $(VENV) __pycache__ */__pycache__ .pytest_cache
	find . -name '*.pyc' -delete
	@echo "Cleaned build artifacts."
