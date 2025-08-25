# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## CloudCoil - Modern Kubernetes Client for Python

CloudCoil is an async-first Python SDK for Kubernetes that provides elegant Pythonic syntax, full type safety, and built-in testing utilities.

## Common Development Commands

### Testing
```bash
make test                    # Run all tests with pytest (4 parallel workers)
pytest tests/test_sync_e2e.py::test_name  # Run a single test
```

### Code Quality
```bash
make lint                    # Run ruff linter and mypy type checker
make fix-lint                # Auto-fix linting issues with ruff
make prepare-for-pr          # Run fix-lint, lint, and tests before PR
```

### Git and DCO Requirements
```bash
# All commits must include DCO sign-off
git commit -s -m "Your commit message"

# Or add DCO to existing commit
git commit --amend -s
```

**Important**: 
- This project requires Developer Certificate of Origin (DCO) sign-off on all commits. Always use `git commit -s` to automatically add the required `Signed-off-by` line.
- The sign-off will use the name and email configured in git (`git config user.name` and `git config user.email`)
- Do NOT manually add additional Signed-off-by lines in the commit message - let git handle it automatically with the -s flag
- The current repository is configured with: Sambhav Kothari <sambhavs.email@gmail.com>

### Documentation
```bash
make docs-serve              # Serve documentation locally with mkdocs
make docs-deploy             # Deploy docs to GitHub Pages
```

### Model Generation
```bash
make gen-models              # Generate base apimachinery models
make gen-all-repos           # Generate all model repositories
cloudcoil-model-codegen      # CLI tool for generating models (reads from pyproject.toml)
```

## Architecture Overview

### Core Components

1. **Client Module** (`cloudcoil/`)
   - `client/_api_client.py`: Main client implementation with sync/async variants
   - `client/_config.py`: Kubernetes configuration management
   - `resource.py`: Resource CRUD operations and watchers
   - Uses httpx for all network operations

2. **Code Generation** (`cloudcoil/codegen/`)
   - Transforms Kubernetes OpenAPI/CRD specs into Pydantic models
   - Uses Jinja2 templates in `templates/` directory
   - Supports import rewriting and custom transformations
   - Configuration in `pyproject.toml` under `[tool.cloudcoil.modelgen.*]`

3. **Testing Framework** (`cloudcoil/_testing/`)
   - Custom pytest plugin providing K8s fixtures
   - `test_cluster` fixture for k3d cluster management
   - `test_config` fixture for client configuration
   - Supports both async and sync test patterns

4. **Model Organization**
   - Base models in `cloudcoil/output/` (auto-generated)
   - Integration models in separate repos under `cloudcoil-models-*`
   - Each model package has its own versioning

### Key Design Patterns

1. **Builder APIs** - Three styles for resource creation:
   - Direct Pydantic model initialization
   - Fluent builder with lambda chains
   - Context manager builder for nested structures

2. **Async-First** - All operations have async and sync variants:
   - Async methods are the primary implementation
   - Sync methods wrap async with `sync()` decorator

3. **Type Safety**:
   - Full Pydantic models for all K8s resources
   - Custom MyPy plugin for dynamic resources
   - Runtime validation and serialization

4. **Resource Operations**:
   - CRUD operations on Resource class instances
   - Watch operations with async iterators
   - Patch support with strategic merge

## Python Style Patterns and Preferences

### Import Organization
Always organize imports in this order with blank lines between groups:
```python
# Standard library imports
import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Type, TypeVar

# Third-party imports
import httpx
from pydantic import BaseModel, TypeAdapter

# Local imports
from cloudcoil.apimachinery import Status
from cloudcoil.errors import APIError, ResourceNotFound
```

### Naming Conventions
- **Classes**: PascalCase (e.g., `APIClient`, `BaseResource`, `ResourceList`)
- **Functions/methods**: snake_case (e.g., `get_model`, `wait_for`, `create_resource`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `DEFAULT_PAGE_LIMIT`, `_WATCH_TIMEOUT_SECONDS`)
- **Private items**: Leading underscore (e.g., `_BaseAPIClient`, `_build_url`)
- **Type variables**: Single uppercase or descriptive (e.g., `T = TypeVar("T", bound="Resource")`)
- **Module private constants**: Leading underscore + uppercase (e.g., `_DEFAULT_TIMEOUT`)

### Docstring Style
Use Google-style docstrings with clear sections:
```python
def scale(self, replicas: int) -> Self:
    """Scale the resource to the specified number of replicas.

    Args:
        replicas: The desired number of replicas

    Returns:
        The updated resource after scaling

    Raises:
        ValueError: If the resource does not support scaling
        ResourceNotFound: If the resource does not exist
    """
```

### Type Annotations
- Always use type hints for function signatures
- Use `Self` for methods that return the instance
- Import types conditionally when needed for type checking only:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from cloudcoil.client._config import Config
  ```
- Prefer specific types over `Any` when possible
- Use `TypeVar` with bounds for generic types
- Use `Literal` for specific string values instead of plain `str`

### Error Handling
- Create custom exception hierarchy based on base exceptions
- Use specific exceptions for different error cases:
  ```python
  raise ResourceNotFound(f"Resource {name} not found in namespace {namespace}")
  ```
- Always include context in error messages
- Log errors at appropriate levels before re-raising

### Logging
```python
# Create logger at module level
logger = logging.getLogger(__name__)

# Use structured logging with placeholders
logger.debug("Getting resource: %s", url)
logger.warning("Deleting all resources: kind=%s namespace=%s", kind, namespace)
```

### Async/Sync Pattern
- Implement async version first, sync version wraps async
- Async methods use same name as sync (not prefixed with `async_`)
- Keep method signatures identical between async and sync versions
- Use `sync()` decorator for sync wrappers

### Class Design
- Use `@classmethod` for factory methods
- Use `@property` for computed attributes
- Use `@overload` for methods with multiple signatures
- Keep inheritance hierarchies shallow
- Prefer composition over inheritance where appropriate

### Method Organization
Order methods in classes as:
1. Class variables and constants
2. `__init__` and other special methods
3. Class methods (`@classmethod`)
4. Properties (`@property`)
5. Public methods
6. Private methods (prefixed with `_`)

### Pydantic Model Patterns
- Use Pydantic BaseModel for all data structures
- Configure models with `model_config` class variable
- Use field validators for complex validation
- Prefer `model_validate` over direct instantiation for untrusted data
- Use `ConfigDict` for model configuration

### General Patterns
- Keep functions focused on single responsibility
- Use context managers for resource management
- Prefer explicit over implicit
- Use descriptive variable names
- Avoid abbreviations except well-known ones (e.g., `ctx`, `cfg`)
- Chain method calls on new lines for readability
- Use trailing commas in multi-line structures

## Testing Patterns

### Test Organization
- Place all tests in `/tests` directory
- Separate async and sync test implementations
- Use descriptive test names that explain what is being tested
- Group related tests in classes when appropriate

### Test Fixtures
- Use `test_cluster` fixture for k3d cluster access
- Use `test_config` fixture for client configuration
- Fixtures handle setup and teardown automatically
- Tests can share clusters for performance

### Testing Best Practices
- Write both async and sync test variants
- Test error cases and edge conditions
- Use specific assertions with clear messages
- Keep tests focused and independent
- Mock external dependencies when appropriate

## Project Structure Patterns

### Module Organization
- Public API exposed in `__init__.py` with explicit `__all__`
- Private modules/packages use leading underscore
- Type stubs indicated by `py.typed` file
- Clear separation of concerns: client, resources, errors, config

### API Design
- Provide multiple styles for different use cases (direct, fluent, context manager)
- Maintain consistency between sync and async interfaces
- Use builder patterns for complex object construction
- Support method chaining where it improves readability

## Model Generation Workflow

1. Models are configured in `pyproject.toml` sections
2. Use `cloudcoil-model-codegen` to generate from specs
3. Models use cookiecutter template from `/cookiecutter`
4. Each model package is published as `cloudcoil-models-{name}`
5. Import rewriting ensures CloudCoil client compatibility