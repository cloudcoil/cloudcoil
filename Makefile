.PHONY: test
test:
	uv run --frozen pytest

.PHONY: lint
lint:
	uv run --frozen ruff check cloudcoil tests
	uv run --frozen ruff format --check cloudcoil tests
	uv run --frozen mypy -p cloudcoil

.PHONY: fix-lint
fix-lint:
	uv run --frozen ruff format cloudcoil tests
	uv run --frozen ruff check --fix --unsafe-fixes cloudcoil tests

.PHONY: docs-deploy
docs-deploy:
	rm -rf docs/index.md
	cp README.md docs/index.md
	uv run --frozen mkdocs gh-deploy --force

.PHONY: docs-serve
docs-serve:
	rm -rf docs/index.md
	cp README.md docs/index.md
	uv run --frozen mkdocs serve

.PHONY: prepare-for-pr
prepare-for-pr: fix-lint lint test
	@echo "========"
	@echo "It looks good! :)"
	@echo "Make sure to commit all changes!"
	@echo "========"

.PHONY: gen-models
gen-models:
	rm -rf cloudcoil/apimachinery.py
	uv run --frozen cloudcoil-model-codegen
	$(MAKE) fix-lint