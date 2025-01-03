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
	rm -rf cloudcoil/apimachinery.py
	uv run python scripts/apimachinery_gen.py
	uv run datamodel-codegen \
		--input processed_swagger.json \
		--snake-case-field \
		--target-python-version 3.10 \
		--output output \
		--output-model-type pydantic_v2.BaseModel \
		--enum-field-as-literal all \
		--input-file-type jsonschema \
		--disable-appending-item-suffix \
		--disable-timestamp \
		--base-class cloudcoil._pydantic.BaseModel \
		--use-annotated \
		--use-default-kwarg \
		--use-default
	mv output/apimachinery.py cloudcoil/apimachinery.py
	rm -rf cloudcoil/kinds
	uv run cloudcoil-model-codegen
	$(MAKE) fix-lint