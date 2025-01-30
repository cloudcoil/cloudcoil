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


REPOS := $(shell ls models | sed 's/\/$$//')

gen-all-repos: $(addprefix gen-repo-,$(REPOS))

publish-all-repos: $(addprefix publish-repo-,$(REPOS))

gen-repo-%:
	rm -rf output/models-$*
	uvx cookiecutter --no-input --output-dir=output --config-file=models/$*/cookiecutter.yaml cookiecutter _config_dir=$$PWD/models/$*

# publish-repo-% creates a repo in cloudcoil/models-$* if it doesn't exist, and pushes the generated code to it
# It should not force push to the repo and instead change all the existing files in the repo to match the generated code
# Check if the repo exists using gh
# If it doesn't exist, create it
# If it does exist, change all the existing files in the repo to match the generated code
# Push the generated code to the repo
publish-repo-%: gen-repo-%
	@echo "Publishing to cloudcoil/models-$*"
	@if ! gh repo view cloudcoil/models-$* >/dev/null 2>&1; then \
		gh repo create cloudcoil/models-$* --add-readme --public --description "Generated model repository for $*" && gh repo edit --add-topic cloudcoil --add-topic cloudcoil-models cloudcoil/models-$*; \
	fi
	@rm -rf tmp/models-$*
	@mkdir -p tmp/models-$*
	@cd tmp/models-$* && \
		git clone https://github.com/cloudcoil/models-$*.git . || git init && \
		git remote add origin https://github.com/cloudcoil/models-$*.git || true && \
		git rm -rf . && \
		git config user.name "github-actions[bot]" && \
		git config user.email "github-actions[bot]@users.noreply.github.com" && \
		cp -a ../../output/models-$*/. . && \
		git add -A && \
		git diff --cached --quiet || git commit -m "Update generated code" && \
		git push -u origin HEAD:main
