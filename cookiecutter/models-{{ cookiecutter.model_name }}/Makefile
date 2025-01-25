.PHONY: test
test:
	uv run python -m pytest

.PHONY: lint
lint:
	uv run ruff check cloudcoil tests
	uv run ruff format --check cloudcoil tests
	uv run mypy -p cloudcoil.models.{{cookiecutter.module_name}} 

.PHONY: fix-lint
fix-lint:
	uv run ruff format cloudcoil tests
	uv run ruff check --fix --unsafe-fixes cloudcoil tests

.PHONY: docs-deploy
docs-deploy:
	rm -rf docs/index.md
	cp README.md docs/index.md
	uv run mkdocs gh-deploy --force

.PHONY: docs-serve
docs-serve:
	rm -rf docs/index.md
	cp README.md docs/index.md
	uv run mkdocs serve

.PHONY: prepare-for-pr
prepare-for-pr: fix-lint lint test
	@echo "========"
	@echo "It looks good! :)"
	@echo "Make sure to commit all changes!"
	@echo "========"

.PHONY: gen-models
gen-models:
	rm -rf cloudcoil/models
	uv run cloudcoil-model-codegen
	$(MAKE) fix-lint
