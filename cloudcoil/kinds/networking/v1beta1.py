# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field

from cloudcoil._pydantic import BaseModel
from cloudcoil.resources import Resource, ResourceList

from ... import apimachinery


class ParentReference(BaseModel):
    group: Annotated[
        Optional[str],
        Field(description="Group is the group of the object being referenced."),
    ] = None
    name: Annotated[str, Field(description="Name is the name of the object being referenced.")]
    namespace: Annotated[
        Optional[str],
        Field(description="Namespace is the namespace of the object being referenced."),
    ] = None
    resource: Annotated[
        str,
        Field(description="Resource is the resource of the object being referenced."),
    ]


class ServiceCIDRSpec(BaseModel):
    cidrs: Annotated[
        Optional[List[str]],
        Field(
            description='CIDRs defines the IP blocks in CIDR notation (e.g. "192.168.0.0/24" or "2001:db8::/64") from which to assign service cluster IPs. Max of two CIDRs is allowed, one of each IP family. This field is immutable.'
        ),
    ] = None


class IPAddressSpec(BaseModel):
    parent_ref: Annotated[
        ParentReference,
        Field(
            alias="parentRef",
            description="ParentRef references the resource that an IPAddress is attached to. An IPAddress must reference a parent object.",
        ),
    ]


class IPAddress(Resource):
    api_version: Annotated[
        Optional[Literal["networking.k8s.io/v1beta1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "networking.k8s.io/v1beta1"
    kind: Annotated[
        Optional[Literal["IPAddress"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "IPAddress"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="Standard object's metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata"
        ),
    ] = None
    spec: Annotated[
        Optional[IPAddressSpec],
        Field(
            description="spec is the desired state of the IPAddress. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#spec-and-status"
        ),
    ] = None


IPAddressList = ResourceList["IPAddress"]


class ServiceCIDRStatus(BaseModel):
    conditions: Annotated[
        Optional[List[apimachinery.Condition]],
        Field(
            description="conditions holds an array of metav1.Condition that describe the state of the ServiceCIDR. Current service state"
        ),
    ] = None


class ServiceCIDR(Resource):
    api_version: Annotated[
        Optional[Literal["networking.k8s.io/v1beta1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "networking.k8s.io/v1beta1"
    kind: Annotated[
        Optional[Literal["ServiceCIDR"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ServiceCIDR"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="Standard object's metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata"
        ),
    ] = None
    spec: Annotated[
        Optional[ServiceCIDRSpec],
        Field(
            description="spec is the desired state of the ServiceCIDR. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#spec-and-status"
        ),
    ] = None
    status: Annotated[
        Optional[ServiceCIDRStatus],
        Field(
            description="status represents the current state of the ServiceCIDR. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#spec-and-status"
        ),
    ] = None


ServiceCIDRList = ResourceList["ServiceCIDR"]
