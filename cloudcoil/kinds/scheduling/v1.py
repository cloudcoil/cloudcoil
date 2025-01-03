# Generated by cloudcoil-model-codegen v0.0.0
# DO NOT EDIT

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import Field

from cloudcoil.resources import Resource, ResourceList

from ... import apimachinery


class PriorityClass(Resource):
    api_version: Annotated[
        Optional[Literal["scheduling.k8s.io/v1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "scheduling.k8s.io/v1"
    description: Annotated[
        Optional[str],
        Field(
            description="description is an arbitrary string that usually provides guidelines on when this priority class should be used."
        ),
    ] = None
    global_default: Annotated[
        Optional[bool],
        Field(
            alias="globalDefault",
            description="globalDefault specifies whether this PriorityClass should be considered as the default priority for pods that do not have any priority class. Only one PriorityClass can be marked as `globalDefault`. However, if more than one PriorityClasses exists with their `globalDefault` field set to true, the smallest value of such global default PriorityClasses will be used as the default priority.",
        ),
    ] = None
    kind: Annotated[
        Optional[Literal["PriorityClass"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "PriorityClass"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="Standard object's metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata"
        ),
    ] = None
    preemption_policy: Annotated[
        Optional[str],
        Field(
            alias="preemptionPolicy",
            description="preemptionPolicy is the Policy for preempting pods with lower priority. One of Never, PreemptLowerPriority. Defaults to PreemptLowerPriority if unset.",
        ),
    ] = None
    value: Annotated[
        int,
        Field(
            description="value represents the integer value of this priority class. This is the actual priority that pods receive when they have the name of this class in their pod spec."
        ),
    ]


PriorityClassList = ResourceList["PriorityClass"]
