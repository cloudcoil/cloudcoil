.PHONY: test
test:
	uv run pytest

.PHONY: lint
lint:
	uv run ruff check cloudcoil tests
	uv run ruff format --check cloudcoil tests
	uv run mypy cloudcoil

.PHONY: fix-lint
fix-lint:
	uv run ruff check --fix cloudcoil tests
	uv run ruff format cloudcoil tests

.PHONY: docs-serve
docs-serve:
	uv run mkdocs serve

.PHONY: prepare-for-pr
prepare-for-pr: fix-lint lint test
	@echo "========"
	@echo "It looks good! :)"
	@echo "Make sure to commit all changes!"
	@echo "========"
