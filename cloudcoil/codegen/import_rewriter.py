import os
import re
from collections import deque
from pathlib import Path


def get_package_from_path(file_path: str, base_dir: str) -> str:
    """Convert a file path to a package path relative to base_dir."""
    abs_base_dir = os.path.abspath(base_dir)
    abs_file_path = os.path.abspath(file_path)

    if not abs_file_path.startswith(abs_base_dir):
        raise ValueError(f"File path {file_path} is not under base directory {base_dir}")

    rel_path = os.path.relpath(abs_file_path, abs_base_dir)
    rel_path = os.path.splitext(rel_path)[0]  # Remove .py extension
    return rel_path.replace(os.sep, ".")


def process_file(file_path: str, base_package: str, base_dir: str) -> None:
    """
    Process a single Python file and rewrite its imports.

    Args:
        file_path: The path to the Python file
        base_package: The base package being processed
        base_dir: The base working directory
    """
    current_package = get_package_from_path(file_path, base_dir)
    current_parts = current_package.split(".")
    base_parts = base_package.split(".")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"(from\s+)(\.+)([a-zA-Z0-9_.]*)(\s+)(import.*)"

    modifications = []
    modified_content = content

    for match in re.finditer(pattern, content):
        from_part = match.group(1)
        dots = match.group(2)
        module = match.group(3)
        space = match.group(4)
        import_part = match.group(5)

        if len(dots) > len(current_parts):
            raise ValueError(f"Invalid import in {file_path}: {match.group(0)}")
        if len(dots) > len(current_parts) - len(base_parts):
            root_pkg = ".".join(current_parts[: len(current_parts) - len(dots)])
            if module:
                new_module = f"{root_pkg}.{module}" if root_pkg else module
            else:
                new_module = root_pkg
            new_import = f"{from_part}{new_module}{space}{import_part}"
            old_import = match.group(0)
            modified_content = modified_content.replace(old_import, new_import)
            modifications.append((old_import, new_import))

    if modifications:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(modified_content)


def rewrite_imports(base_package: str, base_dir: str | Path) -> None:
    """
    Recursively rewrite imports in all Python files under the specified package.

    Args:
        base_package: The package to process (e.g., 'cloudcoil.models.kubernetes')
        base_dir: The base working directory
    """
    package_path = os.path.join(base_dir, base_package.replace(".", os.sep))

    if not os.path.exists(package_path):
        raise ValueError(f"Package path {package_path} does not exist")

    dirs_to_process = deque([package_path])

    while dirs_to_process:
        current_dir = dirs_to_process.popleft()

        for item in os.listdir(current_dir):
            full_path = os.path.join(current_dir, item)

            if os.path.isdir(full_path):
                if os.path.exists(os.path.join(full_path, "__init__.py")):
                    dirs_to_process.append(full_path)

            elif item.endswith(".py"):
                process_file(full_path, base_package, str(base_dir))
