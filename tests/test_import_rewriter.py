from pathlib import Path
from textwrap import dedent

import pytest

from cloudcoil.codegen.import_rewriter import get_package_from_path, process_file


@pytest.fixture
def temp_python_file(tmp_path):
    def _create_file(content: str, subpath: Path = Path("")) -> tuple[Path, Path]:
        nested_dir = tmp_path / "cloudcoil" / "resources" / subpath
        nested_dir.mkdir(parents=True)
        file_path = nested_dir / "test_module.py"
        file_path.write_text(dedent(content))
        return tmp_path, file_path

    return _create_file


def test_get_package_from_path():
    base_dir = "/base/dir"
    assert get_package_from_path("/base/dir/pkg/module.py", base_dir) == "pkg.module"
    assert get_package_from_path("/base/dir/pkg/sub/module.py", base_dir) == "pkg.sub.module"

    with pytest.raises(ValueError):
        get_package_from_path("/other/dir/module.py", base_dir)


def test_process_file_simple_case(temp_python_file):
    content = """
    from ..models import MyModel
    from ...core import utils
    from ....foo import bar
    """
    base_dir, file_path = temp_python_file(content, Path("foo"))
    process_file(file_path, "cloudcoil.resources", str(base_dir))

    result = file_path.read_text()
    # Leaves imports unchanged if they do not cross package boundaries
    assert "from ..models import MyModel" in result
    # Rewrites imports that cross package boundaries
    assert "from cloudcoil.core import utils" in result
    # Rewrites imports that cross multiple package boundaries
    assert "from foo import bar" in result


def test_process_file_with_multiple_imports(temp_python_file):
    content = """
    from . import local
    from ... import parent
    from ...sibling import something
    from ....grandparent.module import item
    """
    base_dir, file_path = temp_python_file(content, Path("sibling"))
    process_file(file_path, "cloudcoil.resources", base_dir)

    result = file_path.read_text()
    assert "from . import local" in result  # Single dot imports shouldn't change
    assert "from cloudcoil import parent" in result
    assert "from cloudcoil.sibling import something" in result
    assert "from grandparent.module import item" in result


def test_process_file_complex_case(temp_python_file):
    content = """
    import os
    from typing import List
    
    from . import local
    from .. import parent
    from ..sibling.module import (
        Thing1,
        Thing2,
        Thing3,
    )
    from ...top.module import item
    
    def my_function():
        pass
    """
    base_dir, file_path = temp_python_file(content)
    process_file(file_path, "cloudcoil.resources", base_dir)

    result = file_path.read_text()
    assert "import os" in result
    assert "from typing import List" in result
    assert "from . import local" in result
    assert "from cloudcoil import parent" in result
    assert "from cloudcoil.sibling.module import (" in result
    assert "from top.module import item" in result
    assert "def my_function():" in result


def test_process_file_invalid_dots(temp_python_file):
    content = """
    from .............. import too_many_dots
    """
    base_dir, file_path = temp_python_file(content)
    with pytest.raises(ValueError):
        process_file(file_path, "cloudcoil.resources", base_dir)
