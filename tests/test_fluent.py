from cloudcoil.apimachinery import APIResource, APIResourceList, Quantity


def test_root():
    with Quantity.new() as q:
        q.root("1")
    o = q.build()
    assert o.root == "1"


def test_context_builder():
    with APIResource.new() as resource:
        resource.name("pods")
        resource.kind("Pod")
        resource.namespaced(True)
        resource.singular_name("pod")
        resource.verbs(["get", "list", "watch"])
    o = resource.build()
    assert o.name == "pods"
    assert o.kind == "Pod"


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
        lambda cls: cls.name("pods")
        .kind("Pod")
        .namespaced(True)
        .singular_name("pod")
        .verbs(["get", "list"])
    )

    built = resources.build()
    assert len(built) == 1
    assert built[0].name == "pods"


def test_complex_builder():
    api_list = (
        APIResourceList.builder()
        .group_version("v1")
        .resources(
            lambda resources: resources.add(
                lambda cls: cls.name("pods")
                .kind("Pod")
                .namespaced(True)
                .singular_name("pod")
                .verbs(["get", "list"])
            ).add(
                lambda cls: cls.name("services")
                .kind("Service")
                .namespaced(True)
                .singular_name("service")
                .verbs(["get", "list"])
            )
        )
        .build()
    )

    assert api_list.group_version == "v1"
    assert len(api_list.resources) == 2
    assert api_list.resources[0].name == "pods"
    assert api_list.resources[1].name == "services"


def test_list_callback():
    def create_resources(
        resources: APIResource.ListBuilder,
    ) -> APIResource.ListBuilder:
        return resources.add(
            lambda cls: cls.name("pods")
            .kind("Pod")
            .namespaced(True)
            .singular_name("pod")
            .verbs(["get", "list"])
        ).add(
            lambda cls: cls.name("services")
            .kind("Service")
            .namespaced(True)
            .singular_name("service")
            .verbs(["get", "list"])
        )

    api_list = APIResourceList.builder().group_version("v1").resources(create_resources).build()

    assert len(api_list.resources) == 2
    assert api_list.resources[0].name == "pods"
    assert api_list.resources[1].name == "services"


def test_nested_context():
    with APIResourceList.new() as api_list:
        api_list.group_version("v1")
        with api_list.resources() as resources:
            with resources.add() as resource:
                resource.name("pods").kind("Pod")
                resource.namespaced(True)
                resource.singular_name("pod")
                resource.verbs(["get", "list"])
            with resources.add() as resource:
                resource.name("services")
                resource.kind("Service")
                resource.namespaced(True)
                resource.singular_name("service")
                resource.verbs(["get", "list"])

    output = api_list.build()
    assert output.group_version == "v1"
    assert len(output.resources) == 2
    assert output.resources[0].name == "pods"
    assert output.resources[1].name == "services"
