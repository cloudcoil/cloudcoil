"""Complete upstream schemas must generate, import, and validate without hints."""

import gzip
import subprocess
import sys
from pathlib import Path

import pytest

from cloudcoil.codegen.generator import ModelConfig, generate


@pytest.mark.parametrize(
    "name,kind,version,spec",
    [
        (
            "flux",
            "HelmRelease",
            "helm.toolkit.fluxcd.io/v2",
            {
                "interval": "10m",
                "chart": {
                    "spec": {
                        "chart": "podinfo",
                        "sourceRef": {"kind": "HelmRepository", "name": "podinfo"},
                    }
                },
            },
        ),
        (
            "cert_manager",
            "Certificate",
            "cert-manager.io/v1",
            {"secretName": "tls", "issuerRef": {"name": "issuer"}},
        ),
        ("prometheus", "Prometheus", "monitoring.coreos.com/v1", {"replicas": 1}),
        (
            "kpack",
            "Image",
            "kpack.io/v1alpha2",
            {
                "tag": "example.com/image",
                "builder": {"name": "builder", "kind": "Builder"},
                "source": {"git": {"url": "https://example.com/repo", "revision": "main"}},
            },
        ),
    ],
)
def test_upstream_without_hints(tmp_path, name, kind, version, spec):
    source = tmp_path / "schema.json"
    source.write_bytes(
        gzip.decompress((Path(__file__).parent / "data" / "crds" / f"{name}.json.gz").read_bytes())
    )
    namespace = f"generated_{name}"
    generate(ModelConfig(namespace=namespace, input_=str(source), output=tmp_path))
    script = f"""
from {namespace} import get_model
from cloudcoil.resources import Resource
from pydantic import ValidationError
model = get_model({kind!r}, api_version={version!r})
assert issubclass(model, Resource)
resource = model.model_validate({{"metadata": {{"name": "sample"}}, "spec": {spec!r}}})
assert resource.name == "sample"
assert resource.gvk().api_version == {version!r}
assert resource.model_dump(by_alias=True)["kind"] == {kind!r}
assert model.builder().metadata(lambda meta: meta.name("built")).spec(resource.spec).build().name == "built"
try:
    model.model_validate({{"apiVersion": "wrong/v1", "kind": "Wrong"}})
except ValidationError:
    pass
else:
    raise AssertionError("Resource identity must be validated")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
