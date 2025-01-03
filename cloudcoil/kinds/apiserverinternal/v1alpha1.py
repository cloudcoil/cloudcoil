# Generated by cloudcoil-model-codegen v0.0.0
# DO NOT EDIT

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field

from cloudcoil._pydantic import BaseModel
from cloudcoil.resources import Resource, ResourceList

from ... import apimachinery


class ServerStorageVersion(BaseModel):
    api_server_id: Annotated[
        Optional[str],
        Field(alias="apiServerID", description="The ID of the reporting API server."),
    ] = None
    decodable_versions: Annotated[
        Optional[List[str]],
        Field(
            alias="decodableVersions",
            description="The API server can decode objects encoded in these versions. The encodingVersion must be included in the decodableVersions.",
        ),
    ] = None
    encoding_version: Annotated[
        Optional[str],
        Field(
            alias="encodingVersion",
            description="The API server encodes the object to this version when persisting it in the backend (e.g., etcd).",
        ),
    ] = None
    served_versions: Annotated[
        Optional[List[str]],
        Field(
            alias="servedVersions",
            description="The API server can serve these versions. DecodableVersions must include all ServedVersions.",
        ),
    ] = None


class StorageVersionSpec(BaseModel):
    pass


class StorageVersionCondition(BaseModel):
    last_transition_time: Annotated[
        Optional[apimachinery.Time],
        Field(
            alias="lastTransitionTime",
            description="Last time the condition transitioned from one status to another.",
        ),
    ] = None
    message: Annotated[
        str,
        Field(description="A human readable message indicating details about the transition."),
    ]
    observed_generation: Annotated[
        Optional[int],
        Field(
            alias="observedGeneration",
            description="If set, this represents the .metadata.generation that the condition was set based upon.",
        ),
    ] = None
    reason: Annotated[str, Field(description="The reason for the condition's last transition.")]
    status: Annotated[
        str, Field(description="Status of the condition, one of True, False, Unknown.")
    ]
    type: Annotated[str, Field(description="Type of the condition.")]


class StorageVersionStatus(BaseModel):
    common_encoding_version: Annotated[
        Optional[str],
        Field(
            alias="commonEncodingVersion",
            description="If all API server instances agree on the same encoding storage version, then this field is set to that version. Otherwise this field is left empty. API servers should finish updating its storageVersionStatus entry before serving write operations, so that this field will be in sync with the reality.",
        ),
    ] = None
    conditions: Annotated[
        Optional[List[StorageVersionCondition]],
        Field(description="The latest available observations of the storageVersion's state."),
    ] = None
    storage_versions: Annotated[
        Optional[List[ServerStorageVersion]],
        Field(
            alias="storageVersions",
            description="The reported versions per API server instance.",
        ),
    ] = None


class StorageVersion(Resource):
    api_version: Annotated[
        Optional[Literal["internal.apiserver.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "internal.apiserver.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["StorageVersion"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "StorageVersion"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(description="The name is <group>.<resource>."),
    ] = None
    spec: Annotated[
        StorageVersionSpec,
        Field(description="Spec is an empty spec. It is here to comply with Kubernetes API style."),
    ]
    status: Annotated[
        StorageVersionStatus,
        Field(
            description="API server instances report the version they can decode and the version they encode objects to when persisting objects in the backend."
        ),
    ]


StorageVersionList = ResourceList["StorageVersion"]
