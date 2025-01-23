from typing import List

from cloudcoil.apimachinery import APIResource, APIResourceList


def test_simple_builder():
    resource = (
        APIResource.builder()
        .name("pods")
        .kind("Pod")
        .namespaced(True)
        .singular_name("pod")
        .verbs(["get", "list", "watch"])
        .build()
    )

    assert resource.name == "pods"
    assert resource.kind == "Pod"
    assert resource.namespaced is True
    assert resource.singular_name == "pod"
    assert resource.verbs == ["get", "list", "watch"]


def test_builder_immutability():
    builder = APIResource.builder().name("pods")
    builder2 = builder.kind("Pod")

    assert builder._attrs != builder2._attrs
    assert "kind" not in builder._attrs
    assert builder2._attrs["kind"] == "Pod"


def test_list_builder():
    resources = APIResource.list_builder()
    resources = resources.add(
        lambda cls: cls.builder()
        .name("pods")
        .kind("Pod")
        .namespaced(True)
        .singular_name("pod")
        .verbs(["get", "list"])
        .build()
    )
    resources = resources.add(
        lambda cls: cls(
            name="services",
            kind="Service",
            namespaced=True,
            singular_name="service",
            verbs=["get", "list"],
        )
    )

    built = resources.build()
    assert len(built) == 2
    assert built[0].name == "pods"
    assert built[1].name == "services"


def test_complex_builder():
    api_list = (
        APIResourceList.builder()
        .group_version("v1")
        .resources(
            lambda cls: [
                cls.builder()
                .name("pods")
                .kind("Pod")
                .namespaced(True)
                .singular_name("pod")
                .verbs(["get", "list"])
                .build(),
                cls.builder()
                .name("services")
                .kind("Service")
                .namespaced(True)
                .singular_name("service")
                .verbs(["get", "list"])
                .build(),
            ]
        )
        .build()
    )

    assert api_list.group_version == "v1"
    assert len(api_list.resources) == 2
    assert api_list.resources[0].name == "pods"
    assert api_list.resources[1].name == "services"


def test_list_callback():
    def create_resources(cls: type[APIResource]) -> List[APIResource]:
        return [
            cls.builder()
            .name("pods")
            .kind("Pod")
            .namespaced(True)
            .singular_name("pod")
            .verbs(["get", "list"])
            .build(),
            cls.builder()
            .name("services")
            .kind("Service")
            .namespaced(True)
            .singular_name("service")
            .verbs(["get", "list"])
            .build(),
        ]

    api_list = APIResourceList.builder().group_version("v1").resources(create_resources).build()

    assert len(api_list.resources) == 2
    assert api_list.resources[0].name == "pods"
    assert api_list.resources[1].name == "services"
