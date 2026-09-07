import json
import subprocess
import sys

import pytest

from cloudcoil.codegen.generator import ModelConfig, generate


@pytest.mark.parametrize("split_modules", [False, True])
def test_nullable_nested_builders(tmp_path, split_modules):
    schema = {
        "definitions": {
            "Child": {
                "type": "object",
                "nullable": True,
                "properties": {"value": {"type": "string"}},
            },
            "Parent": {
                "type": "object",
                "properties": {
                    "child": {"$ref": "#/definitions/Child"},
                    "children": {"type": "array", "items": {"$ref": "#/definitions/Child"}},
                },
            },
        }
    }
    source = tmp_path / "schema.json"
    schema_text = json.dumps(schema)
    if split_modules:
        schema_text = schema_text.replace("Child", "child.Child").replace("Parent", "parent.Parent")
    source.write_text(schema_text)
    generate(
        ModelConfig(
            namespace="nullable_models",
            input=str(source),
            output=tmp_path,
            mode="base",
            transformations=[{"match": "^(.+)$", "replace": r"models.\g<1>"}],
        )
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from nullable_models.models import Parent

assert Parent.builder().child(None).build().child is None
parent = Parent.builder().child(lambda b: b.value('callback')).build()
assert parent.child.value == 'callback'
parent = Parent.builder().children(lambda items: items.add(lambda b: b.value('list'))).build()
assert parent.children[0].value == 'list'
with Parent.new() as builder:
    with builder.child() as child:
        child.value('context')
    with builder.children() as children:
        with children.add() as child:
            child.value('list context')
parent = builder.build()
assert parent.child.value == 'context'
assert parent.children[0].value == 'list context'
""".replace(
                "from nullable_models.models import Parent",
                "from nullable_models.models.parent import Parent"
                if split_modules
                else "from nullable_models.models import Parent",
            ),
        ],
        cwd=tmp_path,
        check=True,
    )
