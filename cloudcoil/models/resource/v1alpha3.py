# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import Field

from cloudcoil.client import BaseModel, Resource

from ..apimachinery import utils
from ..apimachinery import v1 as v1_1
from ..core import v1


class CELDeviceSelector(BaseModel):
    expression: Annotated[
        str,
        Field(
            description='Expression is a CEL expression which evaluates a single device. It must evaluate to true when the device under consideration satisfies the desired criteria, and false when it does not. Any other result is an error and causes allocation of devices to abort.\n\nThe expression\'s input is an object named "device", which carries the following properties:\n - driver (string): the name of the driver which defines this device.\n - attributes (map[string]object): the device\'s attributes, grouped by prefix\n   (e.g. device.attributes["dra.example.com"] evaluates to an object with all\n   of the attributes which were prefixed by "dra.example.com".\n - capacity (map[string]object): the device\'s capacities, grouped by prefix.\n\nExample: Consider a device with driver="dra.example.com", which exposes two attributes named "model" and "ext.example.com/family" and which exposes one capacity named "modules". This input to this expression would have the following fields:\n\n    device.driver\n    device.attributes["dra.example.com"].model\n    device.attributes["ext.example.com"].family\n    device.capacity["dra.example.com"].modules\n\nThe device.driver field can be used to check for a specific driver, either as a high-level precondition (i.e. you only want to consider devices from this driver) or as part of a multi-clause expression that is meant to consider devices from different drivers.\n\nThe value type of each attribute is defined by the device definition, and users who write these expressions must consult the documentation for their specific drivers. The value type of each capacity is Quantity.\n\nIf an unknown prefix is used as a lookup in either device.attributes or device.capacity, an empty map will be returned. Any reference to an unknown field will cause an evaluation error and allocation to abort.\n\nA robust expression should check for the existence of attributes before referencing them.\n\nFor ease of use, the cel.bind() function is enabled, and can be used to simplify expressions that access multiple attributes with the same domain. For example:\n\n    cel.bind(dra, device.attributes["dra.example.com"], dra.someBool && dra.anotherBool)\n\nThe length of the expression must be smaller or equal to 10 Ki. The cost of evaluating it is also limited based on the estimated number of logical steps.'
        ),
    ]


class DeviceAttribute(BaseModel):
    bool: Annotated[Optional[bool], Field(description="BoolValue is a true/false value.")] = None
    int: Annotated[Optional[int], Field(description="IntValue is a number.")] = None
    string: Annotated[
        Optional[str],
        Field(description="StringValue is a string. Must not be longer than 64 characters."),
    ] = None
    version: Annotated[
        Optional[str],
        Field(
            description="VersionValue is a semantic version according to semver.org spec 2.0.0. Must not be longer than 64 characters."
        ),
    ] = None


class DeviceConstraint(BaseModel):
    match_attribute: Annotated[
        Optional[str],
        Field(
            alias="matchAttribute",
            description='MatchAttribute requires that all devices in question have this attribute and that its type and value are the same across those devices.\n\nFor example, if you specified "dra.example.com/numa" (a hypothetical example!), then only devices in the same NUMA node will be chosen. A device which does not have that attribute will not be chosen. All devices should use a value of the same type for this attribute because that is part of its specification, but if one device doesn\'t, then it also will not be chosen.\n\nMust include the domain qualifier.',
        ),
    ] = None
    requests: Annotated[
        Optional[List[str]],
        Field(
            description="Requests is a list of the one or more requests in this claim which must co-satisfy this constraint. If a request is fulfilled by multiple devices, then all of the devices must satisfy the constraint. If this is not specified, this constraint applies to all requests in this claim."
        ),
    ] = None


class DeviceRequestAllocationResult(BaseModel):
    admin_access: Annotated[
        Optional[bool],
        Field(
            alias="adminAccess",
            description="AdminAccess indicates that this device was allocated for administrative access. See the corresponding request field for a definition of mode.\n\nThis is an alpha field and requires enabling the DRAAdminAccess feature gate. Admin access is disabled if this field is unset or set to false, otherwise it is enabled.",
        ),
    ] = None
    device: Annotated[
        str,
        Field(
            description="Device references one device instance via its name in the driver's resource pool. It must be a DNS label."
        ),
    ]
    driver: Annotated[
        str,
        Field(
            description="Driver specifies the name of the DRA driver whose kubelet plugin should be invoked to process the allocation once the claim is needed on a node.\n\nMust be a DNS subdomain and should end with a DNS domain owned by the vendor of the driver."
        ),
    ]
    pool: Annotated[
        str,
        Field(
            description="This name together with the driver name and the device name field identify which device was allocated (`<driver name>/<pool name>/<device name>`).\n\nMust not be longer than 253 characters and may contain one or more DNS sub-domains separated by slashes."
        ),
    ]
    request: Annotated[
        str,
        Field(
            description="Request is the name of the request in the claim which caused this device to be allocated. Multiple devices may have been allocated per request."
        ),
    ]


class DeviceSelector(BaseModel):
    cel: Annotated[
        Optional[CELDeviceSelector],
        Field(description="CEL contains a CEL expression for selecting a device."),
    ] = None


class NetworkDeviceData(BaseModel):
    hardware_address: Annotated[
        Optional[str],
        Field(
            alias="hardwareAddress",
            description="HardwareAddress represents the hardware address (e.g. MAC Address) of the device's network interface.\n\nMust not be longer than 128 characters.",
        ),
    ] = None
    interface_name: Annotated[
        Optional[str],
        Field(
            alias="interfaceName",
            description="InterfaceName specifies the name of the network interface associated with the allocated device. This might be the name of a physical or virtual network interface being configured in the pod.\n\nMust not be longer than 256 characters.",
        ),
    ] = None
    ips: Annotated[
        Optional[List[str]],
        Field(
            description='IPs lists the network addresses assigned to the device\'s network interface. This can include both IPv4 and IPv6 addresses. The IPs are in the CIDR notation, which includes both the address and the associated subnet mask. e.g.: "192.0.2.5/24" for IPv4 and "2001:db8::5/64" for IPv6.'
        ),
    ] = None


class ResourceClaimConsumerReference(BaseModel):
    api_group: Annotated[
        Optional[str],
        Field(
            alias="apiGroup",
            description="APIGroup is the group for the resource being referenced. It is empty for the core API. This matches the group in the APIVersion that is used when creating the resources.",
        ),
    ] = None
    name: Annotated[str, Field(description="Name is the name of resource being referenced.")]
    resource: Annotated[
        str,
        Field(description='Resource is the type of resource being referenced, for example "pods".'),
    ]
    uid: Annotated[
        str,
        Field(description="UID identifies exactly one incarnation of the resource."),
    ]


class ResourcePool(BaseModel):
    generation: Annotated[
        int,
        Field(
            description="Generation tracks the change in a pool over time. Whenever a driver changes something about one or more of the resources in a pool, it must change the generation in all ResourceSlices which are part of that pool. Consumers of ResourceSlices should only consider resources from the pool with the highest generation number. The generation may be reset by drivers, which should be fine for consumers, assuming that all ResourceSlices in a pool are updated to match or deleted.\n\nCombined with ResourceSliceCount, this mechanism enables consumers to detect pools which are comprised of multiple ResourceSlices and are in an incomplete state."
        ),
    ]
    name: Annotated[
        str,
        Field(
            description="Name is used to identify the pool. For node-local devices, this is often the node name, but this is not required.\n\nIt must not be longer than 253 characters and must consist of one or more DNS sub-domains separated by slashes. This field is immutable."
        ),
    ]
    resource_slice_count: Annotated[
        int,
        Field(
            alias="resourceSliceCount",
            description="ResourceSliceCount is the total number of ResourceSlices in the pool at this generation number. Must be greater than zero.\n\nConsumers can use this to check whether they have seen all ResourceSlices belonging to the same pool.",
        ),
    ]


class BasicDevice(BaseModel):
    attributes: Annotated[
        Optional[Dict[str, DeviceAttribute]],
        Field(
            description="Attributes defines the set of attributes for this device. The name of each attribute must be unique in that set.\n\nThe maximum number of attributes and capacities combined is 32."
        ),
    ] = None
    capacity: Annotated[
        Optional[Dict[str, utils.Quantity]],
        Field(
            description="Capacity defines the set of capacities for this device. The name of each capacity must be unique in that set.\n\nThe maximum number of attributes and capacities combined is 32."
        ),
    ] = None


class Device(BaseModel):
    basic: Annotated[
        Optional[BasicDevice], Field(description="Basic defines one device instance.")
    ] = None
    name: Annotated[
        str,
        Field(
            description="Name is unique identifier among all devices managed by the driver in the pool. It must be a DNS label."
        ),
    ]


class DeviceRequest(BaseModel):
    admin_access: Annotated[
        Optional[bool],
        Field(
            alias="adminAccess",
            description="AdminAccess indicates that this is a claim for administrative access to the device(s). Claims with AdminAccess are expected to be used for monitoring or other management services for a device.  They ignore all ordinary claims to the device with respect to access modes and any resource allocations.\n\nThis is an alpha field and requires enabling the DRAAdminAccess feature gate. Admin access is disabled if this field is unset or set to false, otherwise it is enabled.",
        ),
    ] = None
    allocation_mode: Annotated[
        Optional[str],
        Field(
            alias="allocationMode",
            description="AllocationMode and its related fields define how devices are allocated to satisfy this request. Supported values are:\n\n- ExactCount: This request is for a specific number of devices.\n  This is the default. The exact number is provided in the\n  count field.\n\n- All: This request is for all of the matching devices in a pool.\n  Allocation will fail if some devices are already allocated,\n  unless adminAccess is requested.\n\nIf AlloctionMode is not specified, the default mode is ExactCount. If the mode is ExactCount and count is not specified, the default count is one. Any other requests must specify this field.\n\nMore modes may get added in the future. Clients must refuse to handle requests with unknown modes.",
        ),
    ] = None
    count: Annotated[
        Optional[int],
        Field(
            description='Count is used only when the count mode is "ExactCount". Must be greater than zero. If AllocationMode is ExactCount and this field is not specified, the default is one.'
        ),
    ] = None
    device_class_name: Annotated[
        str,
        Field(
            alias="deviceClassName",
            description="DeviceClassName references a specific DeviceClass, which can define additional configuration and selectors to be inherited by this request.\n\nA class is required. Which classes are available depends on the cluster.\n\nAdministrators may use this to restrict which devices may get requested by only installing classes with selectors for permitted devices. If users are free to request anything without restrictions, then administrators can create an empty DeviceClass for users to reference.",
        ),
    ]
    name: Annotated[
        str,
        Field(
            description="Name can be used to reference this request in a pod.spec.containers[].resources.claims entry and in a constraint of the claim.\n\nMust be a DNS label."
        ),
    ]
    selectors: Annotated[
        Optional[List[DeviceSelector]],
        Field(
            description="Selectors define criteria which must be satisfied by a specific device in order for that device to be considered for this request. All selectors must be satisfied for a device to be considered."
        ),
    ] = None


class OpaqueDeviceConfiguration(BaseModel):
    driver: Annotated[
        str,
        Field(
            description="Driver is used to determine which kubelet plugin needs to be passed these configuration parameters.\n\nAn admission policy provided by the driver developer could use this to decide whether it needs to validate them.\n\nMust be a DNS subdomain and should end with a DNS domain owned by the vendor of the driver."
        ),
    ]
    parameters: Annotated[
        utils.RawExtension,
        Field(
            description='Parameters can contain arbitrary data. It is the responsibility of the driver developer to handle validation and versioning. Typically this includes self-identification and a version ("kind" + "apiVersion" for Kubernetes types), with conversion between different versions.\n\nThe length of the raw data must be smaller or equal to 10 Ki.'
        ),
    ]


class ResourceSliceSpec(BaseModel):
    all_nodes: Annotated[
        Optional[bool],
        Field(
            alias="allNodes",
            description="AllNodes indicates that all nodes have access to the resources in the pool.\n\nExactly one of NodeName, NodeSelector and AllNodes must be set.",
        ),
    ] = None
    devices: Annotated[
        Optional[List[Device]],
        Field(
            description="Devices lists some or all of the devices in this pool.\n\nMust not have more than 128 entries."
        ),
    ] = None
    driver: Annotated[
        str,
        Field(
            description="Driver identifies the DRA driver providing the capacity information. A field selector can be used to list only ResourceSlice objects with a certain driver name.\n\nMust be a DNS subdomain and should end with a DNS domain owned by the vendor of the driver. This field is immutable."
        ),
    ]
    node_name: Annotated[
        Optional[str],
        Field(
            alias="nodeName",
            description="NodeName identifies the node which provides the resources in this pool. A field selector can be used to list only ResourceSlice objects belonging to a certain node.\n\nThis field can be used to limit access from nodes to ResourceSlices with the same node name. It also indicates to autoscalers that adding new nodes of the same type as some old node might also make new resources available.\n\nExactly one of NodeName, NodeSelector and AllNodes must be set. This field is immutable.",
        ),
    ] = None
    node_selector: Annotated[
        Optional[v1.NodeSelector],
        Field(
            alias="nodeSelector",
            description="NodeSelector defines which nodes have access to the resources in the pool, when that pool is not limited to a single node.\n\nMust use exactly one term.\n\nExactly one of NodeName, NodeSelector and AllNodes must be set.",
        ),
    ] = None
    pool: Annotated[
        ResourcePool,
        Field(description="Pool describes the pool that this ResourceSlice belongs to."),
    ]


class AllocatedDeviceStatus(BaseModel):
    conditions: Annotated[
        Optional[List[v1_1.Condition]],
        Field(
            description="Conditions contains the latest observation of the device's state. If the device has been configured according to the class and claim config references, the `Ready` condition should be True."
        ),
    ] = None
    data: Annotated[
        Optional[utils.RawExtension],
        Field(
            description="Data contains arbitrary driver-specific data.\n\nThe length of the raw data must be smaller or equal to 10 Ki."
        ),
    ] = None
    device: Annotated[
        str,
        Field(
            description="Device references one device instance via its name in the driver's resource pool. It must be a DNS label."
        ),
    ]
    driver: Annotated[
        str,
        Field(
            description="Driver specifies the name of the DRA driver whose kubelet plugin should be invoked to process the allocation once the claim is needed on a node.\n\nMust be a DNS subdomain and should end with a DNS domain owned by the vendor of the driver."
        ),
    ]
    network_data: Annotated[
        Optional[NetworkDeviceData],
        Field(
            alias="networkData",
            description="NetworkData contains network-related information specific to the device.",
        ),
    ] = None
    pool: Annotated[
        str,
        Field(
            description="This name together with the driver name and the device name field identify which device was allocated (`<driver name>/<pool name>/<device name>`).\n\nMust not be longer than 253 characters and may contain one or more DNS sub-domains separated by slashes."
        ),
    ]


class DeviceAllocationConfiguration(BaseModel):
    opaque: Annotated[
        Optional[OpaqueDeviceConfiguration],
        Field(description="Opaque provides driver-specific configuration parameters."),
    ] = None
    requests: Annotated[
        Optional[List[str]],
        Field(
            description="Requests lists the names of requests where the configuration applies. If empty, its applies to all requests."
        ),
    ] = None
    source: Annotated[
        str,
        Field(
            description="Source records whether the configuration comes from a class and thus is not something that a normal user would have been able to set or from a claim."
        ),
    ]


class DeviceAllocationResult(BaseModel):
    config: Annotated[
        Optional[List[DeviceAllocationConfiguration]],
        Field(
            description="This field is a combination of all the claim and class configuration parameters. Drivers can distinguish between those based on a flag.\n\nThis includes configuration parameters for drivers which have no allocated devices in the result because it is up to the drivers which configuration parameters they support. They can silently ignore unknown configuration parameters."
        ),
    ] = None
    results: Annotated[
        Optional[List[DeviceRequestAllocationResult]],
        Field(description="Results lists all allocated devices."),
    ] = None


class DeviceClaimConfiguration(BaseModel):
    opaque: Annotated[
        Optional[OpaqueDeviceConfiguration],
        Field(description="Opaque provides driver-specific configuration parameters."),
    ] = None
    requests: Annotated[
        Optional[List[str]],
        Field(
            description="Requests lists the names of requests where the configuration applies. If empty, it applies to all requests."
        ),
    ] = None


class DeviceClassConfiguration(BaseModel):
    opaque: Annotated[
        Optional[OpaqueDeviceConfiguration],
        Field(description="Opaque provides driver-specific configuration parameters."),
    ] = None


class DeviceClassSpec(BaseModel):
    config: Annotated[
        Optional[List[DeviceClassConfiguration]],
        Field(
            description="Config defines configuration parameters that apply to each device that is claimed via this class. Some classses may potentially be satisfied by multiple drivers, so each instance of a vendor configuration applies to exactly one driver.\n\nThey are passed to the driver, but are not considered while allocating the claim."
        ),
    ] = None
    selectors: Annotated[
        Optional[List[DeviceSelector]],
        Field(
            description="Each selector must be satisfied by a device which is claimed via this class."
        ),
    ] = None


class ResourceSlice(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    kind: Annotated[
        Optional[Literal["ResourceSlice"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceSlice"
    metadata: Annotated[
        Optional[v1_1.ObjectMeta], Field(description="Standard object metadata")
    ] = None
    spec: Annotated[
        ResourceSliceSpec,
        Field(
            description="Contains the information published by the driver.\n\nChanging the spec automatically increments the metadata.generation number."
        ),
    ]


class ResourceSliceList(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    items: Annotated[
        List[ResourceSlice],
        Field(description="Items is the list of resource ResourceSlices."),
    ]
    kind: Annotated[
        Optional[Literal["ResourceSliceList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceSliceList"
    metadata: Annotated[Optional[v1_1.ListMeta], Field(description="Standard list metadata")] = None


class AllocationResult(BaseModel):
    devices: Annotated[
        Optional[DeviceAllocationResult],
        Field(description="Devices is the result of allocating devices."),
    ] = None
    node_selector: Annotated[
        Optional[v1.NodeSelector],
        Field(
            alias="nodeSelector",
            description="NodeSelector defines where the allocated resources are available. If unset, they are available everywhere.",
        ),
    ] = None


class DeviceClaim(BaseModel):
    config: Annotated[
        Optional[List[DeviceClaimConfiguration]],
        Field(
            description="This field holds configuration for multiple potential drivers which could satisfy requests in this claim. It is ignored while allocating the claim."
        ),
    ] = None
    constraints: Annotated[
        Optional[List[DeviceConstraint]],
        Field(
            description="These constraints must be satisfied by the set of devices that get allocated for the claim."
        ),
    ] = None
    requests: Annotated[
        Optional[List[DeviceRequest]],
        Field(
            description="Requests represent individual requests for distinct devices which must all be satisfied. If empty, nothing needs to be allocated."
        ),
    ] = None


class DeviceClass(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    kind: Annotated[
        Optional[Literal["DeviceClass"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "DeviceClass"
    metadata: Annotated[
        Optional[v1_1.ObjectMeta], Field(description="Standard object metadata")
    ] = None
    spec: Annotated[
        DeviceClassSpec,
        Field(
            description="Spec defines what can be allocated and how to configure it.\n\nThis is mutable. Consumers have to be prepared for classes changing at any time, either because they get updated or replaced. Claim allocations are done once based on whatever was set in classes at the time of allocation.\n\nChanging the spec automatically increments the metadata.generation number."
        ),
    ]


class DeviceClassList(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    items: Annotated[List[DeviceClass], Field(description="Items is the list of resource classes.")]
    kind: Annotated[
        Optional[Literal["DeviceClassList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "DeviceClassList"
    metadata: Annotated[Optional[v1_1.ListMeta], Field(description="Standard list metadata")] = None


class ResourceClaimSpec(BaseModel):
    devices: Annotated[
        Optional[DeviceClaim],
        Field(description="Devices defines how to request devices."),
    ] = None


class ResourceClaimStatus(BaseModel):
    allocation: Annotated[
        Optional[AllocationResult],
        Field(description="Allocation is set once the claim has been allocated successfully."),
    ] = None
    devices: Annotated[
        Optional[List[AllocatedDeviceStatus]],
        Field(
            description="Devices contains the status of each device allocated for this claim, as reported by the driver. This can include driver-specific information. Entries are owned by their respective drivers."
        ),
    ] = None
    reserved_for: Annotated[
        Optional[List[ResourceClaimConsumerReference]],
        Field(
            alias="reservedFor",
            description="ReservedFor indicates which entities are currently allowed to use the claim. A Pod which references a ResourceClaim which is not reserved for that Pod will not be started. A claim that is in use or might be in use because it has been reserved must not get deallocated.\n\nIn a cluster with multiple scheduler instances, two pods might get scheduled concurrently by different schedulers. When they reference the same ResourceClaim which already has reached its maximum number of consumers, only one pod can be scheduled.\n\nBoth schedulers try to add their pod to the claim.status.reservedFor field, but only the update that reaches the API server first gets stored. The other one fails with an error and the scheduler which issued it knows that it must put the pod back into the queue, waiting for the ResourceClaim to become usable again.\n\nThere can be at most 32 such reservations. This may get increased in the future, but not reduced.",
        ),
    ] = None


class ResourceClaimTemplateSpec(BaseModel):
    metadata: Annotated[
        Optional[v1_1.ObjectMeta],
        Field(
            description="ObjectMeta may contain labels and annotations that will be copied into the ResourceClaim when creating it. No other fields are allowed and will be rejected during validation."
        ),
    ] = None
    spec: Annotated[
        ResourceClaimSpec,
        Field(
            description="Spec for the ResourceClaim. The entire content is copied unchanged into the ResourceClaim that gets created from this template. The same fields as in a ResourceClaim are also valid here."
        ),
    ]


class ResourceClaim(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    kind: Annotated[
        Optional[Literal["ResourceClaim"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceClaim"
    metadata: Annotated[
        Optional[v1_1.ObjectMeta], Field(description="Standard object metadata")
    ] = None
    spec: Annotated[
        ResourceClaimSpec,
        Field(
            description="Spec describes what is being requested and how to configure it. The spec is immutable."
        ),
    ]
    status: Annotated[
        Optional[ResourceClaimStatus],
        Field(
            description="Status describes whether the claim is ready to use and what has been allocated."
        ),
    ] = None


class ResourceClaimList(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    items: Annotated[
        List[ResourceClaim], Field(description="Items is the list of resource claims.")
    ]
    kind: Annotated[
        Optional[Literal["ResourceClaimList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceClaimList"
    metadata: Annotated[Optional[v1_1.ListMeta], Field(description="Standard list metadata")] = None


class ResourceClaimTemplate(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    kind: Annotated[
        Optional[Literal["ResourceClaimTemplate"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceClaimTemplate"
    metadata: Annotated[
        Optional[v1_1.ObjectMeta], Field(description="Standard object metadata")
    ] = None
    spec: Annotated[
        ResourceClaimTemplateSpec,
        Field(
            description="Describes the ResourceClaim that is to be generated.\n\nThis field is immutable. A ResourceClaim will get created by the control plane for a Pod when needed and then not get updated anymore."
        ),
    ]


class ResourceClaimTemplateList(Resource):
    api_version: Annotated[
        Optional[Literal["resource.k8s.io/v1alpha3"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "resource.k8s.io/v1alpha3"
    items: Annotated[
        List[ResourceClaimTemplate],
        Field(description="Items is the list of resource claim templates."),
    ]
    kind: Annotated[
        Optional[Literal["ResourceClaimTemplateList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ResourceClaimTemplateList"
    metadata: Annotated[Optional[v1_1.ListMeta], Field(description="Standard list metadata")] = None
