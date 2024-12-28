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

.PHONY: docs-serve
docs-serve:
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
	uv run python scripts/fetch_schema.py
	uv run datamodel-codegen \
		--input processed_swagger.json \
		--snake-case-field \
		--target-python-version 3.9 \
		--output cloudcoil/models \
		--output-model-type pydantic_v2.BaseModel \
		--enum-field-as-literal all \
		--input-file-type jsonschema \
		--disable-appending-item-suffix \
		--disable-timestamp \
		--base-class cloudcoil.client.Resource \
		--use-annotated \
		--use-default-kwarg \
		--custom-template-dir templates \
		--extra-template-data extra_data.json \
		--additional-imports cloudcoil._pydantic.BaseModel \
		--use-default
	rm -rf cloudcoil/models/__init__.py
	touch cloudcoil/models/__init__.py
	$(MAKE) fix-lint