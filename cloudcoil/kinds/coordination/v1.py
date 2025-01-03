# Generated by cloudcoil-model-codegen v0.0.0
# DO NOT EDIT

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import Field

from cloudcoil._pydantic import BaseModel
from cloudcoil.resources import Resource, ResourceList

from ... import apimachinery


class LeaseSpec(BaseModel):
    acquire_time: Annotated[
        Optional[apimachinery.MicroTime],
        Field(
            alias="acquireTime",
            description="acquireTime is a time when the current lease was acquired.",
        ),
    ] = None
    holder_identity: Annotated[
        Optional[str],
        Field(
            alias="holderIdentity",
            description="holderIdentity contains the identity of the holder of a current lease. If Coordinated Leader Election is used, the holder identity must be equal to the elected LeaseCandidate.metadata.name field.",
        ),
    ] = None
    lease_duration_seconds: Annotated[
        Optional[int],
        Field(
            alias="leaseDurationSeconds",
            description="leaseDurationSeconds is a duration that candidates for a lease need to wait to force acquire it. This is measured against the time of last observed renewTime.",
        ),
    ] = None
    lease_transitions: Annotated[
        Optional[int],
        Field(
            alias="leaseTransitions",
            description="leaseTransitions is the number of transitions of a lease between holders.",
        ),
    ] = None
    preferred_holder: Annotated[
        Optional[str],
        Field(
            alias="preferredHolder",
            description="PreferredHolder signals to a lease holder that the lease has a more optimal holder and should be given up. This field can only be set if Strategy is also set.",
        ),
    ] = None
    renew_time: Annotated[
        Optional[apimachinery.MicroTime],
        Field(
            alias="renewTime",
            description="renewTime is a time when the current holder of a lease has last updated the lease.",
        ),
    ] = None
    strategy: Annotated[
        Optional[str],
        Field(
            description="Strategy indicates the strategy for picking the leader for coordinated leader election. If the field is not specified, there is no active coordination for this lease. (Alpha) Using this field requires the CoordinatedLeaderElection feature gate to be enabled."
        ),
    ] = None


class Lease(Resource):
    api_version: Annotated[
        Optional[Literal["coordination.k8s.io/v1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "coordination.k8s.io/v1"
    kind: Annotated[
        Optional[Literal["Lease"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "Lease"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata"
        ),
    ] = None
    spec: Annotated[
        Optional[LeaseSpec],
        Field(
            description="spec contains the specification of the Lease. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#spec-and-status"
        ),
    ] = None


LeaseList = ResourceList["Lease"]
