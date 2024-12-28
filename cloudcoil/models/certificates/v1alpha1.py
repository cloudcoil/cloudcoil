# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field

from cloudcoil.client import Resource

from ..apimachinery import v1


class ClusterTrustBundleSpec(Resource):
    signer_name: Annotated[
        Optional[str],
        Field(
            alias="signerName",
            description="signerName indicates the associated signer, if any.\n\nIn order to create or update a ClusterTrustBundle that sets signerName, you must have the following cluster-scoped permission: group=certificates.k8s.io resource=signers resourceName=<the signer name> verb=attest.\n\nIf signerName is not empty, then the ClusterTrustBundle object must be named with the signer name as a prefix (translating slashes to colons). For example, for the signer name `example.com/foo`, valid ClusterTrustBundle object names include `example.com:foo:abc` and `example.com:foo:v1`.\n\nIf signerName is empty, then the ClusterTrustBundle object's name must not have such a prefix.\n\nList/watch requests for ClusterTrustBundles can filter on this field using a `spec.signerName=NAME` field selector.",
        ),
    ] = None
    trust_bundle: Annotated[
        str,
        Field(
            alias="trustBundle",
            description="trustBundle contains the individual X.509 trust anchors for this bundle, as PEM bundle of PEM-wrapped, DER-formatted X.509 certificates.\n\nThe data must consist only of PEM certificate blocks that parse as valid X.509 certificates.  Each certificate must include a basic constraints extension with the CA bit set.  The API server will reject objects that contain duplicate certificates, or that use PEM block headers.\n\nUsers of ClusterTrustBundles, including Kubelet, are free to reorder and deduplicate certificate blocks in this file according to their own logic, as well as to drop PEM block headers and inter-block data.",
        ),
    ]


class ClusterTrustBundle(Resource):
    api_version: Annotated[
        Optional[Literal["certificates.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "certificates.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["ClusterTrustBundle"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ClusterTrustBundle"
    metadata: Annotated[
        Optional[v1.ObjectMeta],
        Field(description="metadata contains the object metadata."),
    ] = None
    spec: Annotated[
        ClusterTrustBundleSpec,
        Field(description="spec contains the signer (if any) and trust anchors."),
    ]


class ClusterTrustBundleList(Resource):
    api_version: Annotated[
        Optional[Literal["certificates.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "certificates.k8s.io/v1alpha1"
    items: Annotated[
        List[ClusterTrustBundle],
        Field(description="items is a collection of ClusterTrustBundle objects"),
    ]
    kind: Annotated[
        Optional[Literal["ClusterTrustBundleList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ClusterTrustBundleList"
    metadata: Annotated[
        Optional[v1.ListMeta], Field(description="metadata contains the list metadata.")
    ] = None
