.PHONY: install test lint demo bench clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .

demo:
	blender-automation-skill demo --out out/demo

bench:
	blender-automation-skill bench --out out/bench

clean:
	rm -rf out build dist .pytest_cache .ruff_cache **/__pycache__
