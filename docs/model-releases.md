# Maintaining model packages

The source of each integration is `models/<name>/cookiecutter.yaml` plus its
optional `pyproject.toml`, schema, README, Makefile, and test overlays. Edit these
sources in Cloudcoil; changes made only in a generated repository are overwritten
by the next template update.

## Version update PRs

**Check upstream model versions** runs each weekday and can also be dispatched
manually. `tools/update_model_versions.py` reads `models/upstreams.json`, discovers
final GitHub releases, and updates the schema URLs and generation matrix together.
A single `automation/model-versions` PR contains the available updates. Subsequent
runs update that PR. New upstream major and minor versions are proposed for review,
not merged automatically.

Kubernetes only receives patch updates for the explicitly maintained minor lines.
Adding a minor or removing one at EOL still requires updating the support policy,
cluster CI images, and model matrix together. Prereleases and unrelated chart tags
are excluded. Cloudcoil itself is checked on PyPI; the shared runtime and generation
requirements advance only within their current minor compatibility range. A new
Cloudcoil minor requires a deliberate migration.

To inspect updates without modifying files:

```sh
GH_TOKEN=... uv run --frozen python tools/update_model_versions.py --check
```

The workflow uses the existing `CI_GITHUB_TOKEN` so the generated PR triggers CI.
The token needs access to Cloudcoil and the model repositories, with contents,
pull-request, and workflow write permissions. Never substitute the default
`GITHUB_TOKEN` for operations that must trigger downstream push/release workflows;
[GitHub suppresses those recursive events](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow).

## Validation and release

**Validate model templates** renders and checks changed integrations on a PR.
Shared template changes check every integration. Each job generates from the
published Cloudcoil version, runs lint, mypy, and model tests, builds both
artifacts, and checks for missing generated modules. No release credentials are
provided to this PR workflow.

After merging a source update, the existing **Update Versions** workflow pushes
the rendered templates to each model repository. That repository's **Update
Versions** workflow then:

1. Selects the configured upstream schema version and refreshes the compatible
   Cloudcoil lockfile entry.
2. Generates models and runs lint, type checks, and tests.
3. Compares generated code and package metadata with the last released fingerprint.
   Unchanged packages do not get another release.
4. Allocates `<upstream>.<packaging>` using all published releases, Git tags, and
   PyPI versions. Revisions are compared numerically, and existing draft reservations
   are reused. The first upstream release uses packaging revision `0`.
5. Sets the final package version, refreshes the lockfile, builds a wheel and sdist,
   and checks artifact identity, model completeness, and Cloudcoil dependencies.
6. Pushes a regular commit to `release-<major>.<minor>` and creates or updates a
   draft pinned to that exact commit. If main advances during the job, publication
   stops so an older generation cannot replace the current one.

The first run after adopting fingerprint tracking can produce one packaging
revision for an existing upstream version. Later identical runs are no-ops.

Drafts are the default. To enable publication after validation, set the repository
variable `AUTO_PUBLISH_MODELS=true` in each model repository. The release event
then triggers its existing PyPI trusted publisher. You can also dispatch **Update
Versions** with `publish=true` and `dry_run=false` for a single release run. The
manual workflow defaults to a dry run, which builds and validates without pushing
branches or publishing releases.

Both release workflows serialize concurrent runs. The publisher checks that the
release tag matches the committed package version and installs locked dependencies.
A failed generation or artifact check never publishes a release. If the GitHub
release succeeds but PyPI publishing fails, rerun that release's **PyPI publish**
job; regeneration does not allocate a duplicate version merely to retry an upload.
A published version is immutable, including a yanked version.

## Adding an integration

Add its source config, upstream entry, and resource round-trip tests. Run
`make gen-repo-<name>`, then `make gen-models lint test` and `uv build` inside the
rendered repository. The generator infers Kubernetes resource identities from the
upstream schemas; add configuration overrides only for demonstrated schema issues.

Before publishing a new package, configure a PyPI trusted publisher for owner
`cloudcoil`, repository `models-<name>`, and workflow `pypi_publish.yml`. Ensure the
existing `CI_GITHUB_TOKEN` is available to the new repository. Keep automatic
publication disabled until this setup is complete. Add a core installation extra
only after the model distribution exists on PyPI, so the core lockfile never
requires an unpublished dependency.
