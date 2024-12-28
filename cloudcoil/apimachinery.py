# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Dict, List, Optional, Union

from pydantic import Field, RootModel

from cloudcoil._pydantic import BaseModel


class Quantity(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='Quantity is a fixed-point representation of a number. It provides convenient marshaling/unmarshaling in JSON and YAML, in addition to String() and AsInt64() accessors.\n\nThe serialization format is:\n\n``` <quantity>        ::= <signedNumber><suffix>\n\n\t(Note that <suffix> may be empty, from the "" case in <decimalSI>.)\n\n<digit>           ::= 0 | 1 | ... | 9 <digits>          ::= <digit> | <digit><digits> <number>          ::= <digits> | <digits>.<digits> | <digits>. | .<digits> <sign>            ::= "+" | "-" <signedNumber>    ::= <number> | <sign><number> <suffix>          ::= <binarySI> | <decimalExponent> | <decimalSI> <binarySI>        ::= Ki | Mi | Gi | Ti | Pi | Ei\n\n\t(International System of units; See: http://physics.nist.gov/cuu/Units/binary.html)\n\n<decimalSI>       ::= m | "" | k | M | G | T | P | E\n\n\t(Note that 1024 = 1Ki but 1000 = 1k; I didn\'t choose the capitalization.)\n\n<decimalExponent> ::= "e" <signedNumber> | "E" <signedNumber> ```\n\nNo matter which of the three exponent forms is used, no quantity may represent a number greater than 2^63-1 in magnitude, nor may it have more than 3 decimal places. Numbers larger or more precise will be capped or rounded up. (E.g.: 0.1m will rounded up to 1m.) This may be extended in the future if we require larger or smaller quantities.\n\nWhen a Quantity is parsed from a string, it will remember the type of suffix it had, and will use the same type again when it is serialized.\n\nBefore serializing, Quantity will be put in "canonical form". This means that Exponent/suffix will be adjusted up or down (with a corresponding increase or decrease in Mantissa) such that:\n\n- No precision is lost - No fractional digits will be emitted - The exponent (or suffix) is as large as possible.\n\nThe sign will be omitted unless the number is negative.\n\nExamples:\n\n- 1.5 will be serialized as "1500m" - 1.5Gi will be serialized as "1536Mi"\n\nNote that the quantity will NEVER be internally represented by a floating point number. That is the whole point of this exercise.\n\nNon-canonical values will still parse as long as they are well formed, but will be re-emitted in their canonical form. (So always use canonical form, or don\'t diff.)\n\nThis format is intended to make it difficult to use these numbers without writing some sort of special handling code in the hopes that that will cause implementors to also use a fixed point implementation.'
        ),
    ]


class APIResource(BaseModel):
    categories: Annotated[
        Optional[List[str]],
        Field(
            description="categories is a list of the grouped resources this resource belongs to (e.g. 'all')"
        ),
    ] = None
    group: Annotated[
        Optional[str],
        Field(
            description='group is the preferred group of the resource.  Empty implies the group of the containing resource list. For subresources, this may have a different value, for example: Scale".'
        ),
    ] = None
    kind: Annotated[
        str,
        Field(
            description="kind is the kind for the resource (e.g. 'Foo' is the kind for a resource 'foo')"
        ),
    ]
    name: Annotated[str, Field(description="name is the plural name of the resource.")]
    namespaced: Annotated[
        bool,
        Field(description="namespaced indicates if a resource is namespaced or not."),
    ]
    short_names: Annotated[
        Optional[List[str]],
        Field(
            alias="shortNames",
            description="shortNames is a list of suggested short names of the resource.",
        ),
    ] = None
    singular_name: Annotated[
        str,
        Field(
            alias="singularName",
            description="singularName is the singular name of the resource.  This allows clients to handle plural and singular opaquely. The singularName is more correct for reporting status on a single item and both singular and plural are allowed from the kubectl CLI interface.",
        ),
    ]
    storage_version_hash: Annotated[
        Optional[str],
        Field(
            alias="storageVersionHash",
            description="The hash value of the storage version, the version this resource is converted to when written to the data store. Value must be treated as opaque by clients. Only equality comparison on the value is valid. This is an alpha feature and may change or be removed in the future. The field is populated by the apiserver only if the StorageVersionHash feature gate is enabled. This field will remain optional even if it graduates.",
        ),
    ] = None
    verbs: Annotated[
        List[str],
        Field(
            description="verbs is a list of supported kube verbs (this includes get, list, watch, create, update, patch, delete, deletecollection, and proxy)"
        ),
    ]
    version: Annotated[
        Optional[str],
        Field(
            description="version is the preferred version of the resource.  Empty implies the version of the containing resource list For subresources, this may have a different value, for example: v1 (while inside a v1beta1 version of the core resource's group)\"."
        ),
    ] = None


class FieldSelectorRequirement(BaseModel):
    key: Annotated[
        str,
        Field(description="key is the field selector key that the requirement applies to."),
    ]
    operator: Annotated[
        str,
        Field(
            description="operator represents a key's relationship to a set of values. Valid operators are In, NotIn, Exists, DoesNotExist. The list of operators may grow in the future."
        ),
    ]
    values: Annotated[
        Optional[List[str]],
        Field(
            description="values is an array of string values. If the operator is In or NotIn, the values array must be non-empty. If the operator is Exists or DoesNotExist, the values array must be empty."
        ),
    ] = None


class FieldsV1(BaseModel):
    pass


class GroupVersionForDiscovery(BaseModel):
    group_version: Annotated[
        str,
        Field(
            alias="groupVersion",
            description='groupVersion specifies the API group and version in the form "group/version"',
        ),
    ]
    version: Annotated[
        str,
        Field(
            description='version specifies the version in the form of "version". This is to save the clients the trouble of splitting the GroupVersion.'
        ),
    ]


class LabelSelectorRequirement(BaseModel):
    key: Annotated[str, Field(description="key is the label key that the selector applies to.")]
    operator: Annotated[
        str,
        Field(
            description="operator represents a key's relationship to a set of values. Valid operators are In, NotIn, Exists and DoesNotExist."
        ),
    ]
    values: Annotated[
        Optional[List[str]],
        Field(
            description="values is an array of string values. If the operator is In or NotIn, the values array must be non-empty. If the operator is Exists or DoesNotExist, the values array must be empty. This array is replaced during a strategic merge patch."
        ),
    ] = None


class ListMeta(BaseModel):
    continue_: Annotated[
        Optional[str],
        Field(
            alias="continue",
            description="continue may be set if the user set a limit on the number of items returned, and indicates that the server has more data available. The value is opaque and may be used to issue another request to the endpoint that served this list to retrieve the next set of available objects. Continuing a consistent list may not be possible if the server configuration has changed or more than a few minutes have passed. The resourceVersion field returned when using this continue value will be identical to the value in the first response, unless you have received this token from an error message.",
        ),
    ] = None
    remaining_item_count: Annotated[
        Optional[int],
        Field(
            alias="remainingItemCount",
            description="remainingItemCount is the number of subsequent items in the list which are not included in this list response. If the list request contained label or field selectors, then the number of remaining items is unknown and the field will be left unset and omitted during serialization. If the list is complete (either because it is not chunking or because this is the last chunk), then there are no more remaining items and this field will be left unset and omitted during serialization. Servers older than v1.15 do not set this field. The intended use of the remainingItemCount is *estimating* the size of a collection. Clients should not rely on the remainingItemCount to be set or to be exact.",
        ),
    ] = None
    resource_version: Annotated[
        Optional[str],
        Field(
            alias="resourceVersion",
            description="String that identifies the server's internal version of this object that can be used by clients to determine when objects have changed. Value must be treated as opaque by clients and passed unmodified back to the server. Populated by the system. Read-only. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#concurrency-control-and-consistency",
        ),
    ] = None
    self_link: Annotated[
        Optional[str],
        Field(
            alias="selfLink",
            description="Deprecated: selfLink is a legacy read-only field that is no longer populated by the system.",
        ),
    ] = None


class MicroTime(RootModel[datetime]):
    root: Annotated[
        datetime,
        Field(description="MicroTime is version of Time with microsecond level precision."),
    ]


class OwnerReference(BaseModel):
    api_version: Annotated[
        str, Field(alias="apiVersion", description="API version of the referent.")
    ]
    block_owner_deletion: Annotated[
        Optional[bool],
        Field(
            alias="blockOwnerDeletion",
            description='If true, AND if the owner has the "foregroundDeletion" finalizer, then the owner cannot be deleted from the key-value store until this reference is removed. See https://kubernetes.io/docs/concepts/architecture/garbage-collection/#foreground-deletion for how the garbage collector interacts with this field and enforces the foreground deletion. Defaults to false. To set this field, a user needs "delete" permission of the owner, otherwise 422 (Unprocessable Entity) will be returned.',
        ),
    ] = None
    controller: Annotated[
        Optional[bool],
        Field(description="If true, this reference points to the managing controller."),
    ] = None
    kind: Annotated[
        str,
        Field(
            description="Kind of the referent. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ]
    name: Annotated[
        str,
        Field(
            description="Name of the referent. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names#names"
        ),
    ]
    uid: Annotated[
        str,
        Field(
            description="UID of the referent. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names#uids"
        ),
    ]


class Patch(BaseModel):
    pass


class Preconditions(BaseModel):
    resource_version: Annotated[
        Optional[str],
        Field(alias="resourceVersion", description="Specifies the target ResourceVersion"),
    ] = None
    uid: Annotated[Optional[str], Field(description="Specifies the target UID.")] = None


class ServerAddressByClientCIDR(BaseModel):
    client_cidr: Annotated[
        str,
        Field(
            alias="clientCIDR",
            description="The CIDR with which clients can match their IP to figure out the server address that they should use.",
        ),
    ]
    server_address: Annotated[
        str,
        Field(
            alias="serverAddress",
            description="Address of this server, suitable for a client that matches the above CIDR. This can be a hostname, hostname:port, IP or IP:port.",
        ),
    ]


class StatusCause(BaseModel):
    field: Annotated[
        Optional[str],
        Field(
            description='The field of the resource that has caused this error, as named by its JSON serialization. May include dot and postfix notation for nested attributes. Arrays are zero-indexed.  Fields may appear more than once in an array of causes due to fields having multiple errors. Optional.\n\nExamples:\n  "name" - the field "name" on the current resource\n  "items[0].name" - the field "name" on the first array entry in "items"'
        ),
    ] = None
    message: Annotated[
        Optional[str],
        Field(
            description="A human-readable description of the cause of the error.  This field may be presented as-is to a reader."
        ),
    ] = None
    reason: Annotated[
        Optional[str],
        Field(
            description="A machine-readable description of the cause of the error. If this value is empty there is no information available."
        ),
    ] = None


class StatusDetails(BaseModel):
    causes: Annotated[
        Optional[List[StatusCause]],
        Field(
            description="The Causes array includes more details associated with the StatusReason failure. Not all StatusReasons may provide detailed causes."
        ),
    ] = None
    group: Annotated[
        Optional[str],
        Field(
            description="The group attribute of the resource associated with the status StatusReason."
        ),
    ] = None
    kind: Annotated[
        Optional[str],
        Field(
            description="The kind attribute of the resource associated with the status StatusReason. On some operations may differ from the requested resource Kind. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = None
    name: Annotated[
        Optional[str],
        Field(
            description="The name attribute of the resource associated with the status StatusReason (when there is a single name which can be described)."
        ),
    ] = None
    retry_after_seconds: Annotated[
        Optional[int],
        Field(
            alias="retryAfterSeconds",
            description="If specified, the time in seconds before the operation should be retried. Some errors may indicate the client must take an alternate action - for those errors this field may indicate how long to wait before taking the alternate action.",
        ),
    ] = None
    uid: Annotated[
        Optional[str],
        Field(
            description="UID of the resource. (when there is a single resource which can be described). More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names#uids"
        ),
    ] = None


class Time(RootModel[datetime]):
    root: Annotated[
        datetime,
        Field(
            description="Time is a wrapper around time.Time which supports correct marshaling to YAML and JSON.  Wrappers are provided for many of the factory methods that the time package offers."
        ),
    ]


class RawExtension(BaseModel):
    pass


class IntOrString(RootModel[Union[int, str]]):
    root: Annotated[
        Union[int, str],
        Field(
            description="IntOrString is a type that can hold an int32 or a string.  When used in JSON or YAML marshalling and unmarshalling, it produces or consumes the inner type.  This allows you to have, for example, a JSON field that can accept a name or number."
        ),
    ]


class Info(BaseModel):
    build_date: Annotated[str, Field(alias="buildDate")]
    compiler: str
    git_commit: Annotated[str, Field(alias="gitCommit")]
    git_tree_state: Annotated[str, Field(alias="gitTreeState")]
    git_version: Annotated[str, Field(alias="gitVersion")]
    go_version: Annotated[str, Field(alias="goVersion")]
    major: str
    minor: str
    platform: str


class Condition(BaseModel):
    last_transition_time: Annotated[
        Time,
        Field(
            alias="lastTransitionTime",
            description="lastTransitionTime is the last time the condition transitioned from one status to another. This should be when the underlying condition changed.  If that is not known, then using the time when the API field changed is acceptable.",
        ),
    ]
    message: Annotated[
        str,
        Field(
            description="message is a human readable message indicating details about the transition. This may be an empty string."
        ),
    ]
    observed_generation: Annotated[
        Optional[int],
        Field(
            alias="observedGeneration",
            description="observedGeneration represents the .metadata.generation that the condition was set based upon. For instance, if .metadata.generation is currently 12, but the .status.conditions[x].observedGeneration is 9, the condition is out of date with respect to the current state of the instance.",
        ),
    ] = None
    reason: Annotated[
        str,
        Field(
            description="reason contains a programmatic identifier indicating the reason for the condition's last transition. Producers of specific condition types may define expected values and meanings for this field, and whether the values are considered a guaranteed API. The value should be a CamelCase string. This field may not be empty."
        ),
    ]
    status: Annotated[
        str, Field(description="status of the condition, one of True, False, Unknown.")
    ]
    type: Annotated[
        str,
        Field(description="type of condition in CamelCase or in foo.example.com/CamelCase."),
    ]


class LabelSelector(BaseModel):
    match_expressions: Annotated[
        Optional[List[LabelSelectorRequirement]],
        Field(
            alias="matchExpressions",
            description="matchExpressions is a list of label selector requirements. The requirements are ANDed.",
        ),
    ] = None
    match_labels: Annotated[
        Optional[Dict[str, str]],
        Field(
            alias="matchLabels",
            description='matchLabels is a map of {key,value} pairs. A single {key,value} in the matchLabels map is equivalent to an element of matchExpressions, whose key field is "key", the operator is "In", and the values array contains only "value". The requirements are ANDed.',
        ),
    ] = None


class ManagedFieldsEntry(BaseModel):
    api_version: Annotated[
        Optional[str],
        Field(
            alias="apiVersion",
            description='APIVersion defines the version of this resource that this field set applies to. The format is "group/version" just like the top-level APIVersion field. It is necessary to track the version of a field set because it cannot be automatically converted.',
        ),
    ] = None
    fields_type: Annotated[
        Optional[str],
        Field(
            alias="fieldsType",
            description='FieldsType is the discriminator for the different fields format and version. There is currently only one possible value: "FieldsV1"',
        ),
    ] = None
    fields_v1: Annotated[
        Optional[FieldsV1],
        Field(
            alias="fieldsV1",
            description='FieldsV1 holds the first JSON version format as described in the "FieldsV1" type.',
        ),
    ] = None
    manager: Annotated[
        Optional[str],
        Field(description="Manager is an identifier of the workflow managing these fields."),
    ] = None
    operation: Annotated[
        Optional[str],
        Field(
            description="Operation is the type of operation which lead to this ManagedFieldsEntry being created. The only valid values for this field are 'Apply' and 'Update'."
        ),
    ] = None
    subresource: Annotated[
        Optional[str],
        Field(
            description="Subresource is the name of the subresource used to update that object, or empty string if the object was updated through the main resource. The value of this field is used to distinguish between managers, even if they share the same name. For example, a status update will be distinct from a regular update using the same manager name. Note that the APIVersion field is not related to the Subresource field and it always corresponds to the version of the main resource."
        ),
    ] = None
    time: Annotated[
        Optional[Time],
        Field(
            description="Time is the timestamp of when the ManagedFields entry was added. The timestamp will also be updated if a field is added, the manager changes any of the owned fields value or removes a field. The timestamp does not update when a field is removed from the entry because another manager took it over."
        ),
    ] = None


class ObjectMeta(BaseModel):
    annotations: Annotated[
        Optional[Dict[str, str]],
        Field(
            description="Annotations is an unstructured key value map stored with a resource that may be set by external tools to store and retrieve arbitrary metadata. They are not queryable and should be preserved when modifying objects. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations"
        ),
    ] = None
    creation_timestamp: Annotated[
        Optional[Time],
        Field(
            alias="creationTimestamp",
            description="CreationTimestamp is a timestamp representing the server time when this object was created. It is not guaranteed to be set in happens-before order across separate operations. Clients may not set this value. It is represented in RFC3339 form and is in UTC.\n\nPopulated by the system. Read-only. Null for lists. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata",
        ),
    ] = None
    deletion_grace_period_seconds: Annotated[
        Optional[int],
        Field(
            alias="deletionGracePeriodSeconds",
            description="Number of seconds allowed for this object to gracefully terminate before it will be removed from the system. Only set when deletionTimestamp is also set. May only be shortened. Read-only.",
        ),
    ] = None
    deletion_timestamp: Annotated[
        Optional[Time],
        Field(
            alias="deletionTimestamp",
            description="DeletionTimestamp is RFC 3339 date and time at which this resource will be deleted. This field is set by the server when a graceful deletion is requested by the user, and is not directly settable by a client. The resource is expected to be deleted (no longer visible from resource lists, and not reachable by name) after the time in this field, once the finalizers list is empty. As long as the finalizers list contains items, deletion is blocked. Once the deletionTimestamp is set, this value may not be unset or be set further into the future, although it may be shortened or the resource may be deleted prior to this time. For example, a user may request that a pod is deleted in 30 seconds. The Kubelet will react by sending a graceful termination signal to the containers in the pod. After that 30 seconds, the Kubelet will send a hard termination signal (SIGKILL) to the container and after cleanup, remove the pod from the API. In the presence of network partitions, this object may still exist after this timestamp, until an administrator or automated process can determine the resource is fully terminated. If not set, graceful deletion of the object has not been requested.\n\nPopulated by the system when a graceful deletion is requested. Read-only. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata",
        ),
    ] = None
    finalizers: Annotated[
        Optional[List[str]],
        Field(
            description="Must be empty before the object is deleted from the registry. Each entry is an identifier for the responsible component that will remove the entry from the list. If the deletionTimestamp of the object is non-nil, entries in this list can only be removed. Finalizers may be processed and removed in any order.  Order is NOT enforced because it introduces significant risk of stuck finalizers. finalizers is a shared field, any actor with permission can reorder it. If the finalizer list is processed in order, then this can lead to a situation in which the component responsible for the first finalizer in the list is waiting for a signal (field value, external system, or other) produced by a component responsible for a finalizer later in the list, resulting in a deadlock. Without enforced ordering finalizers are free to order amongst themselves and are not vulnerable to ordering changes in the list."
        ),
    ] = None
    generate_name: Annotated[
        Optional[str],
        Field(
            alias="generateName",
            description="GenerateName is an optional prefix, used by the server, to generate a unique name ONLY IF the Name field has not been provided. If this field is used, the name returned to the client will be different than the name passed. This value will also be combined with a unique suffix. The provided value has the same validation rules as the Name field, and may be truncated by the length of the suffix required to make the value unique on the server.\n\nIf this field is specified and the generated name exists, the server will return a 409.\n\nApplied only if Name is not specified. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#idempotency",
        ),
    ] = None
    generation: Annotated[
        Optional[int],
        Field(
            description="A sequence number representing a specific generation of the desired state. Populated by the system. Read-only."
        ),
    ] = None
    labels: Annotated[
        Optional[Dict[str, str]],
        Field(
            description="Map of string keys and values that can be used to organize and categorize (scope and select) objects. May match selectors of replication controllers and services. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels"
        ),
    ] = None
    managed_fields: Annotated[
        Optional[List[ManagedFieldsEntry]],
        Field(
            alias="managedFields",
            description="ManagedFields maps workflow-id and version to the set of fields that are managed by that workflow. This is mostly for internal housekeeping, and users typically shouldn't need to set or understand this field. A workflow can be the user's name, a controller's name, or the name of a specific apply path like \"ci-cd\". The set of fields is always in the version that the workflow used when modifying the object.",
        ),
    ] = None
    name: Annotated[
        Optional[str],
        Field(
            description="Name must be unique within a namespace. Is required when creating resources, although some resources may allow a client to request the generation of an appropriate name automatically. Name is primarily intended for creation idempotence and configuration definition. Cannot be updated. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names#names"
        ),
    ] = None
    namespace: Annotated[
        Optional[str],
        Field(
            description='Namespace defines the space within which each name must be unique. An empty namespace is equivalent to the "default" namespace, but "default" is the canonical representation. Not all objects are required to be scoped to a namespace - the value of this field for those objects will be empty.\n\nMust be a DNS_LABEL. Cannot be updated. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces'
        ),
    ] = None
    owner_references: Annotated[
        Optional[List[OwnerReference]],
        Field(
            alias="ownerReferences",
            description="List of objects depended by this object. If ALL objects in the list have been deleted, this object will be garbage collected. If this object is managed by a controller, then an entry in this list will point to this controller, with the controller field set to true. There cannot be more than one managing controller.",
        ),
    ] = None
    resource_version: Annotated[
        Optional[str],
        Field(
            alias="resourceVersion",
            description="An opaque value that represents the internal version of this object that can be used by clients to determine when objects have changed. May be used for optimistic concurrency, change detection, and the watch operation on a resource or set of resources. Clients must treat these values as opaque and passed unmodified back to the server. They may only be valid for a particular resource or set of resources.\n\nPopulated by the system. Read-only. Value must be treated as opaque by clients and . More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#concurrency-control-and-consistency",
        ),
    ] = None
    self_link: Annotated[
        Optional[str],
        Field(
            alias="selfLink",
            description="Deprecated: selfLink is a legacy read-only field that is no longer populated by the system.",
        ),
    ] = None
    uid: Annotated[
        Optional[str],
        Field(
            description="UID is the unique in time and space value for this object. It is typically generated by the server on successful creation of a resource and is not allowed to change on PUT operations.\n\nPopulated by the system. Read-only. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names#uids"
        ),
    ] = None