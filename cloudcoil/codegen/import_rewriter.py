import ast
import os
from collections import deque
from pathlib import Path


def get_package_from_path(file_path: str, base_dir: str) -> str:
    """Convert a file path to a package path relative to base_dir."""
    abs_base_dir = os.path.abspath(base_dir)
    abs_file_path = os.path.abspath(file_path)

    if not Path(abs_file_path).is_relative_to(abs_base_dir):
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

    lines = content.splitlines(keepends=True)
    edits = []
    for node in ast.walk(ast.parse(content)):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        if node.level > len(current_parts):
            raise ValueError(f"Invalid relative import in {file_path} at line {node.lineno}")
        if node.level <= len(current_parts) - len(base_parts):
            continue
        root = ".".join(current_parts[: -node.level])
        module = ".".join(part for part in (root, node.module) if part)
        if not module:
            raise ValueError(f"Relative import escapes the package in {file_path}")
        # Change only the import prefix; preserve aliases, comments, and multiline imports.
        line = lines[node.lineno - 1]
        start = len(line.encode()[: node.col_offset].decode())
        old = "from " + "." * node.level + (node.module or "")
        if not line[start:].startswith(old):
            # Unusual whitespace is valid Python: reconstruct the import from its AST.
            replacement = (
                "from "
                + module
                + " import "
                + ", ".join(
                    alias.name + (f" as {alias.asname}" if alias.asname else "")
                    for alias in node.names
                )
            )
            edits.append((node.lineno - 1, node.end_lineno, replacement + "\n"))
        else:
            edits.append(
                (
                    node.lineno - 1,
                    node.lineno,
                    line[:start] + line[start:].replace(old, "from " + module, 1),
                )
            )
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    if edits:
        Path(file_path).write_text("".join(lines), encoding="utf-8")


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
