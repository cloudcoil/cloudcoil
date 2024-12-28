# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field

from cloudcoil.client import BaseModel, Resource

from ..apimachinery import v1


class ApplyConfiguration(BaseModel):
    expression: Annotated[
        Optional[str],
        Field(
            description="expression will be evaluated by CEL to create an apply configuration. ref: https://github.com/google/cel-spec\n\nApply configurations are declared in CEL using object initialization. For example, this CEL expression returns an apply configuration to set a single field:\n\n\tObject{\n\t  spec: Object.spec{\n\t    serviceAccountName: \"example\"\n\t  }\n\t}\n\nApply configurations may not modify atomic structs, maps or arrays due to the risk of accidental deletion of values not included in the apply configuration.\n\nCEL expressions have access to the object types needed to create apply configurations:\n\n- 'Object' - CEL type of the resource object. - 'Object.<fieldName>' - CEL type of object field (such as 'Object.spec') - 'Object.<fieldName1>.<fieldName2>...<fieldNameN>` - CEL type of nested field (such as 'Object.spec.containers')\n\nCEL expressions have access to the contents of the API request, organized into CEL variables as well as some other useful variables:\n\n- 'object' - The object from the incoming request. The value is null for DELETE requests. - 'oldObject' - The existing object. The value is null for CREATE requests. - 'request' - Attributes of the API request([ref](/pkg/apis/admission/types.go#AdmissionRequest)). - 'params' - Parameter resource referred to by the policy binding being evaluated. Only populated if the policy has a ParamKind. - 'namespaceObject' - The namespace object that the incoming object belongs to. The value is null for cluster-scoped resources. - 'variables' - Map of composited variables, from its name to its lazily evaluated value.\n  For example, a variable named 'foo' can be accessed as 'variables.foo'.\n- 'authorizer' - A CEL Authorizer. May be used to perform authorization checks for the principal (user or service account) of the request.\n  See https://pkg.go.dev/k8s.io/apiserver/pkg/cel/library#Authz\n- 'authorizer.requestResource' - A CEL ResourceCheck constructed from the 'authorizer' and configured with the\n  request resource.\n\nThe `apiVersion`, `kind`, `metadata.name` and `metadata.generateName` are always accessible from the root of the object. No other metadata properties are accessible.\n\nOnly property names of the form `[a-zA-Z_.-/][a-zA-Z0-9_.-/]*` are accessible. Required."
        ),
    ] = None


class JSONPatch(BaseModel):
    expression: Annotated[
        Optional[str],
        Field(
            description="expression will be evaluated by CEL to create a [JSON patch](https://jsonpatch.com/). ref: https://github.com/google/cel-spec\n\nexpression must return an array of JSONPatch values.\n\nFor example, this CEL expression returns a JSON patch to conditionally modify a value:\n\n\t  [\n\t    JSONPatch{op: \"test\", path: \"/spec/example\", value: \"Red\"},\n\t    JSONPatch{op: \"replace\", path: \"/spec/example\", value: \"Green\"}\n\t  ]\n\nTo define an object for the patch value, use Object types. For example:\n\n\t  [\n\t    JSONPatch{\n\t      op: \"add\",\n\t      path: \"/spec/selector\",\n\t      value: Object.spec.selector{matchLabels: {\"environment\": \"test\"}}\n\t    }\n\t  ]\n\nTo use strings containing '/' and '~' as JSONPatch path keys, use \"jsonpatch.escapeKey\". For example:\n\n\t  [\n\t    JSONPatch{\n\t      op: \"add\",\n\t      path: \"/metadata/labels/\" + jsonpatch.escapeKey(\"example.com/environment\"),\n\t      value: \"test\"\n\t    },\n\t  ]\n\nCEL expressions have access to the types needed to create JSON patches and objects:\n\n- 'JSONPatch' - CEL type of JSON Patch operations. JSONPatch has the fields 'op', 'from', 'path' and 'value'.\n  See [JSON patch](https://jsonpatch.com/) for more details. The 'value' field may be set to any of: string,\n  integer, array, map or object.  If set, the 'path' and 'from' fields must be set to a\n  [JSON pointer](https://datatracker.ietf.org/doc/html/rfc6901/) string, where the 'jsonpatch.escapeKey()' CEL\n  function may be used to escape path keys containing '/' and '~'.\n- 'Object' - CEL type of the resource object. - 'Object.<fieldName>' - CEL type of object field (such as 'Object.spec') - 'Object.<fieldName1>.<fieldName2>...<fieldNameN>` - CEL type of nested field (such as 'Object.spec.containers')\n\nCEL expressions have access to the contents of the API request, organized into CEL variables as well as some other useful variables:\n\n- 'object' - The object from the incoming request. The value is null for DELETE requests. - 'oldObject' - The existing object. The value is null for CREATE requests. - 'request' - Attributes of the API request([ref](/pkg/apis/admission/types.go#AdmissionRequest)). - 'params' - Parameter resource referred to by the policy binding being evaluated. Only populated if the policy has a ParamKind. - 'namespaceObject' - The namespace object that the incoming object belongs to. The value is null for cluster-scoped resources. - 'variables' - Map of composited variables, from its name to its lazily evaluated value.\n  For example, a variable named 'foo' can be accessed as 'variables.foo'.\n- 'authorizer' - A CEL Authorizer. May be used to perform authorization checks for the principal (user or service account) of the request.\n  See https://pkg.go.dev/k8s.io/apiserver/pkg/cel/library#Authz\n- 'authorizer.requestResource' - A CEL ResourceCheck constructed from the 'authorizer' and configured with the\n  request resource.\n\nCEL expressions have access to [Kubernetes CEL function libraries](https://kubernetes.io/docs/reference/using-api/cel/#cel-options-language-features-and-libraries) as well as:\n\n- 'jsonpatch.escapeKey' - Performs JSONPatch key escaping. '~' and  '/' are escaped as '~0' and `~1' respectively).\n\nOnly property names of the form `[a-zA-Z_.-/][a-zA-Z0-9_.-/]*` are accessible. Required."
        ),
    ] = None


class MatchCondition(BaseModel):
    expression: Annotated[
        str,
        Field(
            description="Expression represents the expression which will be evaluated by CEL. Must evaluate to bool. CEL expressions have access to the contents of the AdmissionRequest and Authorizer, organized into CEL variables:\n\n'object' - The object from the incoming request. The value is null for DELETE requests. 'oldObject' - The existing object. The value is null for CREATE requests. 'request' - Attributes of the admission request(/pkg/apis/admission/types.go#AdmissionRequest). 'authorizer' - A CEL Authorizer. May be used to perform authorization checks for the principal (user or service account) of the request.\n  See https://pkg.go.dev/k8s.io/apiserver/pkg/cel/library#Authz\n'authorizer.requestResource' - A CEL ResourceCheck constructed from the 'authorizer' and configured with the\n  request resource.\nDocumentation on CEL: https://kubernetes.io/docs/reference/using-api/cel/\n\nRequired."
        ),
    ]
    name: Annotated[
        str,
        Field(
            description="Name is an identifier for this match condition, used for strategic merging of MatchConditions, as well as providing an identifier for logging purposes. A good name should be descriptive of the associated expression. Name must be a qualified name consisting of alphanumeric characters, '-', '_' or '.', and must start and end with an alphanumeric character (e.g. 'MyName',  or 'my.name',  or '123-abc', regex used for validation is '([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]') with an optional DNS subdomain prefix and '/' (e.g. 'example.com/MyName')\n\nRequired."
        ),
    ]


class Mutation(BaseModel):
    apply_configuration: Annotated[
        Optional[ApplyConfiguration],
        Field(
            alias="applyConfiguration",
            description="applyConfiguration defines the desired configuration values of an object. The configuration is applied to the admission object using [structured merge diff](https://github.com/kubernetes-sigs/structured-merge-diff). A CEL expression is used to create apply configuration.",
        ),
    ] = None
    json_patch: Annotated[
        Optional[JSONPatch],
        Field(
            alias="jsonPatch",
            description="jsonPatch defines a [JSON patch](https://jsonpatch.com/) operation to perform a mutation to the object. A CEL expression is used to create the JSON patch.",
        ),
    ] = None
    patch_type: Annotated[
        str,
        Field(
            alias="patchType",
            description='patchType indicates the patch strategy used. Allowed values are "ApplyConfiguration" and "JSONPatch". Required.',
        ),
    ]


class NamedRuleWithOperations(BaseModel):
    api_groups: Annotated[
        Optional[List[str]],
        Field(
            alias="apiGroups",
            description="APIGroups is the API groups the resources belong to. '*' is all groups. If '*' is present, the length of the slice must be one. Required.",
        ),
    ] = None
    api_versions: Annotated[
        Optional[List[str]],
        Field(
            alias="apiVersions",
            description="APIVersions is the API versions the resources belong to. '*' is all versions. If '*' is present, the length of the slice must be one. Required.",
        ),
    ] = None
    operations: Annotated[
        Optional[List[str]],
        Field(
            description="Operations is the operations the admission hook cares about - CREATE, UPDATE, DELETE, CONNECT or * for all of those operations and any future admission operations that are added. If '*' is present, the length of the slice must be one. Required."
        ),
    ] = None
    resource_names: Annotated[
        Optional[List[str]],
        Field(
            alias="resourceNames",
            description="ResourceNames is an optional white list of names that the rule applies to.  An empty set means that everything is allowed.",
        ),
    ] = None
    resources: Annotated[
        Optional[List[str]],
        Field(
            description="Resources is a list of resources this rule applies to.\n\nFor example: 'pods' means pods. 'pods/log' means the log subresource of pods. '*' means all resources, but not subresources. 'pods/*' means all subresources of pods. '*/scale' means all scale subresources. '*/*' means all resources and their subresources.\n\nIf wildcard is present, the validation rule will ensure resources do not overlap with each other.\n\nDepending on the enclosing object, subresources might not be allowed. Required."
        ),
    ] = None
    scope: Annotated[
        Optional[str],
        Field(
            description='scope specifies the scope of this rule. Valid values are "Cluster", "Namespaced", and "*" "Cluster" means that only cluster-scoped resources will match this rule. Namespace API objects are cluster-scoped. "Namespaced" means that only namespaced resources will match this rule. "*" means that there are no scope restrictions. Subresources match the scope of their parent resource. Default is "*".'
        ),
    ] = None


class ParamKind(BaseModel):
    api_version: Annotated[
        Optional[str],
        Field(
            alias="apiVersion",
            description='APIVersion is the API group version the resources belong to. In format of "group/version". Required.',
        ),
    ] = None
    kind: Annotated[
        Optional[str],
        Field(description="Kind is the API kind the resources belong to. Required."),
    ] = None


class Variable(BaseModel):
    expression: Annotated[
        str,
        Field(
            description="Expression is the expression that will be evaluated as the value of the variable. The CEL expression has access to the same identifiers as the CEL expressions in Validation."
        ),
    ]
    name: Annotated[
        str,
        Field(
            description='Name is the name of the variable. The name must be a valid CEL identifier and unique among all variables. The variable can be accessed in other expressions through `variables` For example, if name is "foo", the variable will be available as `variables.foo`'
        ),
    ]


class MatchResources(BaseModel):
    exclude_resource_rules: Annotated[
        Optional[List[NamedRuleWithOperations]],
        Field(
            alias="excludeResourceRules",
            description="ExcludeResourceRules describes what operations on what resources/subresources the ValidatingAdmissionPolicy should not care about. The exclude rules take precedence over include rules (if a resource matches both, it is excluded)",
        ),
    ] = None
    match_policy: Annotated[
        Optional[str],
        Field(
            alias="matchPolicy",
            description='matchPolicy defines how the "MatchResources" list is used to match incoming requests. Allowed values are "Exact" or "Equivalent".\n\n- Exact: match a request only if it exactly matches a specified rule. For example, if deployments can be modified via apps/v1, apps/v1beta1, and extensions/v1beta1, but "rules" only included `apiGroups:["apps"], apiVersions:["v1"], resources: ["deployments"]`, a request to apps/v1beta1 or extensions/v1beta1 would not be sent to the ValidatingAdmissionPolicy.\n\n- Equivalent: match a request if modifies a resource listed in rules, even via another API group or version. For example, if deployments can be modified via apps/v1, apps/v1beta1, and extensions/v1beta1, and "rules" only included `apiGroups:["apps"], apiVersions:["v1"], resources: ["deployments"]`, a request to apps/v1beta1 or extensions/v1beta1 would be converted to apps/v1 and sent to the ValidatingAdmissionPolicy.\n\nDefaults to "Equivalent"',
        ),
    ] = None
    namespace_selector: Annotated[
        Optional[v1.LabelSelector],
        Field(
            alias="namespaceSelector",
            description='NamespaceSelector decides whether to run the admission control policy on an object based on whether the namespace for that object matches the selector. If the object itself is a namespace, the matching is performed on object.metadata.labels. If the object is another cluster scoped resource, it never skips the policy.\n\nFor example, to run the webhook on any objects whose namespace is not associated with "runlevel" of "0" or "1";  you will set the selector as follows: "namespaceSelector": {\n  "matchExpressions": [\n    {\n      "key": "runlevel",\n      "operator": "NotIn",\n      "values": [\n        "0",\n        "1"\n      ]\n    }\n  ]\n}\n\nIf instead you want to only run the policy on any objects whose namespace is associated with the "environment" of "prod" or "staging"; you will set the selector as follows: "namespaceSelector": {\n  "matchExpressions": [\n    {\n      "key": "environment",\n      "operator": "In",\n      "values": [\n        "prod",\n        "staging"\n      ]\n    }\n  ]\n}\n\nSee https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/ for more examples of label selectors.\n\nDefault to the empty LabelSelector, which matches everything.',
        ),
    ] = None
    object_selector: Annotated[
        Optional[v1.LabelSelector],
        Field(
            alias="objectSelector",
            description="ObjectSelector decides whether to run the validation based on if the object has matching labels. objectSelector is evaluated against both the oldObject and newObject that would be sent to the cel validation, and is considered to match if either object matches the selector. A null object (oldObject in the case of create, or newObject in the case of delete) or an object that cannot have labels (like a DeploymentRollback or a PodProxyOptions object) is not considered to match. Use the object selector only if the webhook is opt-in, because end users may skip the admission webhook by setting the labels. Default to the empty LabelSelector, which matches everything.",
        ),
    ] = None
    resource_rules: Annotated[
        Optional[List[NamedRuleWithOperations]],
        Field(
            alias="resourceRules",
            description="ResourceRules describes what operations on what resources/subresources the ValidatingAdmissionPolicy matches. The policy cares about an operation if it matches _any_ Rule.",
        ),
    ] = None


class MutatingAdmissionPolicySpec(BaseModel):
    failure_policy: Annotated[
        Optional[str],
        Field(
            alias="failurePolicy",
            description="failurePolicy defines how to handle failures for the admission policy. Failures can occur from CEL expression parse errors, type check errors, runtime errors and invalid or mis-configured policy definitions or bindings.\n\nA policy is invalid if paramKind refers to a non-existent Kind. A binding is invalid if paramRef.name refers to a non-existent resource.\n\nfailurePolicy does not define how validations that evaluate to false are handled.\n\nAllowed values are Ignore or Fail. Defaults to Fail.",
        ),
    ] = None
    match_conditions: Annotated[
        Optional[List[MatchCondition]],
        Field(
            alias="matchConditions",
            description="matchConditions is a list of conditions that must be met for a request to be validated. Match conditions filter requests that have already been matched by the matchConstraints. An empty list of matchConditions matches all requests. There are a maximum of 64 match conditions allowed.\n\nIf a parameter object is provided, it can be accessed via the `params` handle in the same manner as validation expressions.\n\nThe exact matching logic is (in order):\n  1. If ANY matchCondition evaluates to FALSE, the policy is skipped.\n  2. If ALL matchConditions evaluate to TRUE, the policy is evaluated.\n  3. If any matchCondition evaluates to an error (but none are FALSE):\n     - If failurePolicy=Fail, reject the request\n     - If failurePolicy=Ignore, the policy is skipped",
        ),
    ] = None
    match_constraints: Annotated[
        Optional[MatchResources],
        Field(
            alias="matchConstraints",
            description="matchConstraints specifies what resources this policy is designed to validate. The MutatingAdmissionPolicy cares about a request if it matches _all_ Constraints. However, in order to prevent clusters from being put into an unstable state that cannot be recovered from via the API MutatingAdmissionPolicy cannot match MutatingAdmissionPolicy and MutatingAdmissionPolicyBinding. The CREATE, UPDATE and CONNECT operations are allowed.  The DELETE operation may not be matched. '*' matches CREATE, UPDATE and CONNECT. Required.",
        ),
    ] = None
    mutations: Annotated[
        Optional[List[Mutation]],
        Field(
            description="mutations contain operations to perform on matching objects. mutations may not be empty; a minimum of one mutation is required. mutations are evaluated in order, and are reinvoked according to the reinvocationPolicy. The mutations of a policy are invoked for each binding of this policy and reinvocation of mutations occurs on a per binding basis."
        ),
    ] = None
    param_kind: Annotated[
        Optional[ParamKind],
        Field(
            alias="paramKind",
            description="paramKind specifies the kind of resources used to parameterize this policy. If absent, there are no parameters for this policy and the param CEL variable will not be provided to validation expressions. If paramKind refers to a non-existent kind, this policy definition is mis-configured and the FailurePolicy is applied. If paramKind is specified but paramRef is unset in MutatingAdmissionPolicyBinding, the params variable will be null.",
        ),
    ] = None
    reinvocation_policy: Annotated[
        Optional[str],
        Field(
            alias="reinvocationPolicy",
            description='reinvocationPolicy indicates whether mutations may be called multiple times per MutatingAdmissionPolicyBinding as part of a single admission evaluation. Allowed values are "Never" and "IfNeeded".\n\nNever: These mutations will not be called more than once per binding in a single admission evaluation.\n\nIfNeeded: These mutations may be invoked more than once per binding for a single admission request and there is no guarantee of order with respect to other admission plugins, admission webhooks, bindings of this policy and admission policies.  Mutations are only reinvoked when mutations change the object after this mutation is invoked. Required.',
        ),
    ] = None
    variables: Annotated[
        Optional[List[Variable]],
        Field(
            description="variables contain definitions of variables that can be used in composition of other expressions. Each variable is defined as a named CEL expression. The variables defined here will be available under `variables` in other expressions of the policy except matchConditions because matchConditions are evaluated before the rest of the policy.\n\nThe expression of a variable can refer to other variables defined earlier in the list but not those after. Thus, variables must be sorted by the order of first appearance and acyclic."
        ),
    ] = None


class ParamRef(BaseModel):
    name: Annotated[
        Optional[str],
        Field(
            description="`name` is the name of the resource being referenced.\n\n`name` and `selector` are mutually exclusive properties. If one is set, the other must be unset."
        ),
    ] = None
    namespace: Annotated[
        Optional[str],
        Field(
            description="namespace is the namespace of the referenced resource. Allows limiting the search for params to a specific namespace. Applies to both `name` and `selector` fields.\n\nA per-namespace parameter may be used by specifying a namespace-scoped `paramKind` in the policy and leaving this field empty.\n\n- If `paramKind` is cluster-scoped, this field MUST be unset. Setting this field results in a configuration error.\n\n- If `paramKind` is namespace-scoped, the namespace of the object being evaluated for admission will be used when this field is left unset. Take care that if this is left empty the binding must not match any cluster-scoped resources, which will result in an error."
        ),
    ] = None
    parameter_not_found_action: Annotated[
        Optional[str],
        Field(
            alias="parameterNotFoundAction",
            description="`parameterNotFoundAction` controls the behavior of the binding when the resource exists, and name or selector is valid, but there are no parameters matched by the binding. If the value is set to `Allow`, then no matched parameters will be treated as successful validation by the binding. If set to `Deny`, then no matched parameters will be subject to the `failurePolicy` of the policy.\n\nAllowed values are `Allow` or `Deny` Default to `Deny`",
        ),
    ] = None
    selector: Annotated[
        Optional[v1.LabelSelector],
        Field(
            description="selector can be used to match multiple param objects based on their labels. Supply selector: {} to match all resources of the ParamKind.\n\nIf multiple params are found, they are all evaluated with the policy expressions and the results are ANDed together.\n\nOne of `name` or `selector` must be set, but `name` and `selector` are mutually exclusive properties. If one is set, the other must be unset."
        ),
    ] = None


class MutatingAdmissionPolicy(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["MutatingAdmissionPolicy"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "MutatingAdmissionPolicy"
    metadata: Annotated[
        Optional[v1.ObjectMeta],
        Field(
            description="Standard object metadata; More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata."
        ),
    ] = None
    spec: Annotated[
        Optional[MutatingAdmissionPolicySpec],
        Field(description="Specification of the desired behavior of the MutatingAdmissionPolicy."),
    ] = None


class MutatingAdmissionPolicyBindingSpec(BaseModel):
    match_resources: Annotated[
        Optional[MatchResources],
        Field(
            alias="matchResources",
            description="matchResources limits what resources match this binding and may be mutated by it. Note that if matchResources matches a resource, the resource must also match a policy's matchConstraints and matchConditions before the resource may be mutated. When matchResources is unset, it does not constrain resource matching, and only the policy's matchConstraints and matchConditions must match for the resource to be mutated. Additionally, matchResources.resourceRules are optional and do not constraint matching when unset. Note that this is differs from MutatingAdmissionPolicy matchConstraints, where resourceRules are required. The CREATE, UPDATE and CONNECT operations are allowed.  The DELETE operation may not be matched. '*' matches CREATE, UPDATE and CONNECT.",
        ),
    ] = None
    param_ref: Annotated[
        Optional[ParamRef],
        Field(
            alias="paramRef",
            description="paramRef specifies the parameter resource used to configure the admission control policy. It should point to a resource of the type specified in spec.ParamKind of the bound MutatingAdmissionPolicy. If the policy specifies a ParamKind and the resource referred to by ParamRef does not exist, this binding is considered mis-configured and the FailurePolicy of the MutatingAdmissionPolicy applied. If the policy does not specify a ParamKind then this field is ignored, and the rules are evaluated without a param.",
        ),
    ] = None
    policy_name: Annotated[
        Optional[str],
        Field(
            alias="policyName",
            description="policyName references a MutatingAdmissionPolicy name which the MutatingAdmissionPolicyBinding binds to. If the referenced resource does not exist, this binding is considered invalid and will be ignored Required.",
        ),
    ] = None


class MutatingAdmissionPolicyList(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    items: Annotated[
        List[MutatingAdmissionPolicy],
        Field(description="List of ValidatingAdmissionPolicy."),
    ]
    kind: Annotated[
        Optional[Literal["MutatingAdmissionPolicyList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "MutatingAdmissionPolicyList"
    metadata: Annotated[
        Optional[v1.ListMeta],
        Field(
            description="Standard list metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = None


class MutatingAdmissionPolicyBinding(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["MutatingAdmissionPolicyBinding"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "MutatingAdmissionPolicyBinding"
    metadata: Annotated[
        Optional[v1.ObjectMeta],
        Field(
            description="Standard object metadata; More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata."
        ),
    ] = None
    spec: Annotated[
        Optional[MutatingAdmissionPolicyBindingSpec],
        Field(
            description="Specification of the desired behavior of the MutatingAdmissionPolicyBinding."
        ),
    ] = None


class MutatingAdmissionPolicyBindingList(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    items: Annotated[
        List[MutatingAdmissionPolicyBinding],
        Field(description="List of PolicyBinding."),
    ]
    kind: Annotated[
        Optional[Literal["MutatingAdmissionPolicyBindingList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "MutatingAdmissionPolicyBindingList"
    metadata: Annotated[
        Optional[v1.ListMeta],
        Field(
            description="Standard list metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = None
