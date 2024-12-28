# generated by datamodel-codegen:
#   filename:  processed_swagger.json

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field

from cloudcoil._pydantic import BaseModel
from cloudcoil.client import Resource, ResourceList

from ... import apimachinery


class AuditAnnotation(BaseModel):
    key: Annotated[
        str,
        Field(
            description='key specifies the audit annotation key. The audit annotation keys of a ValidatingAdmissionPolicy must be unique. The key must be a qualified name ([A-Za-z0-9][-A-Za-z0-9_.]*) no more than 63 bytes in length.\n\nThe key is combined with the resource name of the ValidatingAdmissionPolicy to construct an audit annotation key: "{ValidatingAdmissionPolicy name}/{key}".\n\nIf an admission webhook uses the same resource name as this ValidatingAdmissionPolicy and the same audit annotation key, the annotation key will be identical. In this case, the first annotation written with the key will be included in the audit event and all subsequent annotations with the same key will be discarded.\n\nRequired.'
        ),
    ]
    value_expression: Annotated[
        str,
        Field(
            alias="valueExpression",
            description="valueExpression represents the expression which is evaluated by CEL to produce an audit annotation value. The expression must evaluate to either a string or null value. If the expression evaluates to a string, the audit annotation is included with the string value. If the expression evaluates to null or empty string the audit annotation will be omitted. The valueExpression may be no longer than 5kb in length. If the result of the valueExpression is more than 10kb in length, it will be truncated to 10kb.\n\nIf multiple ValidatingAdmissionPolicyBinding resources match an API request, then the valueExpression will be evaluated for each binding. All unique values produced by the valueExpressions will be joined together in a comma-separated list.\n\nRequired.",
        ),
    ]


class ExpressionWarning(BaseModel):
    field_ref: Annotated[
        str,
        Field(
            alias="fieldRef",
            description='The path to the field that refers the expression. For example, the reference to the expression of the first item of validations is "spec.validations[0].expression"',
        ),
    ]
    warning: Annotated[
        str,
        Field(
            description="The content of type checking information in a human-readable form. Each line of the warning contains the type that the expression is checked against, followed by the type check error from the compiler."
        ),
    ]


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


class TypeChecking(BaseModel):
    expression_warnings: Annotated[
        Optional[List[ExpressionWarning]],
        Field(
            alias="expressionWarnings",
            description="The type checking warnings for each expression.",
        ),
    ] = None


class Validation(BaseModel):
    expression: Annotated[
        str,
        Field(
            description='Expression represents the expression which will be evaluated by CEL. ref: https://github.com/google/cel-spec CEL expressions have access to the contents of the API request/response, organized into CEL variables as well as some other useful variables:\n\n- \'object\' - The object from the incoming request. The value is null for DELETE requests. - \'oldObject\' - The existing object. The value is null for CREATE requests. - \'request\' - Attributes of the API request([ref](/pkg/apis/admission/types.go#AdmissionRequest)). - \'params\' - Parameter resource referred to by the policy binding being evaluated. Only populated if the policy has a ParamKind. - \'namespaceObject\' - The namespace object that the incoming object belongs to. The value is null for cluster-scoped resources. - \'variables\' - Map of composited variables, from its name to its lazily evaluated value.\n  For example, a variable named \'foo\' can be accessed as \'variables.foo\'.\n- \'authorizer\' - A CEL Authorizer. May be used to perform authorization checks for the principal (user or service account) of the request.\n  See https://pkg.go.dev/k8s.io/apiserver/pkg/cel/library#Authz\n- \'authorizer.requestResource\' - A CEL ResourceCheck constructed from the \'authorizer\' and configured with the\n  request resource.\n\nThe `apiVersion`, `kind`, `metadata.name` and `metadata.generateName` are always accessible from the root of the object. No other metadata properties are accessible.\n\nOnly property names of the form `[a-zA-Z_.-/][a-zA-Z0-9_.-/]*` are accessible. Accessible property names are escaped according to the following rules when accessed in the expression: - \'__\' escapes to \'__underscores__\' - \'.\' escapes to \'__dot__\' - \'-\' escapes to \'__dash__\' - \'/\' escapes to \'__slash__\' - Property names that exactly match a CEL RESERVED keyword escape to \'__{keyword}__\'. The keywords are:\n\t  "true", "false", "null", "in", "as", "break", "const", "continue", "else", "for", "function", "if",\n\t  "import", "let", "loop", "package", "namespace", "return".\nExamples:\n  - Expression accessing a property named "namespace": {"Expression": "object.__namespace__ > 0"}\n  - Expression accessing a property named "x-prop": {"Expression": "object.x__dash__prop > 0"}\n  - Expression accessing a property named "redact__d": {"Expression": "object.redact__underscores__d > 0"}\n\nEquality on arrays with list type of \'set\' or \'map\' ignores element order, i.e. [1, 2] == [2, 1]. Concatenation on arrays with x-kubernetes-list-type use the semantics of the list type:\n  - \'set\': `X + Y` performs a union where the array positions of all elements in `X` are preserved and\n    non-intersecting elements in `Y` are appended, retaining their partial order.\n  - \'map\': `X + Y` performs a merge where the array positions of all keys in `X` are preserved but the values\n    are overwritten by values in `Y` when the key sets of `X` and `Y` intersect. Elements in `Y` with\n    non-intersecting keys are appended, retaining their partial order.\nRequired.'
        ),
    ]
    message: Annotated[
        Optional[str],
        Field(
            description='Message represents the message displayed when validation fails. The message is required if the Expression contains line breaks. The message must not contain line breaks. If unset, the message is "failed rule: {Rule}". e.g. "must be a URL with the host matching spec.host" If the Expression contains line breaks. Message is required. The message must not contain line breaks. If unset, the message is "failed Expression: {Expression}".'
        ),
    ] = None
    message_expression: Annotated[
        Optional[str],
        Field(
            alias="messageExpression",
            description="messageExpression declares a CEL expression that evaluates to the validation failure message that is returned when this rule fails. Since messageExpression is used as a failure message, it must evaluate to a string. If both message and messageExpression are present on a validation, then messageExpression will be used if validation fails. If messageExpression results in a runtime error, the runtime error is logged, and the validation failure message is produced as if the messageExpression field were unset. If messageExpression evaluates to an empty string, a string with only spaces, or a string that contains line breaks, then the validation failure message will also be produced as if the messageExpression field were unset, and the fact that messageExpression produced an empty string/string with only spaces/string with line breaks will be logged. messageExpression has access to all the same variables as the `expression` except for 'authorizer' and 'authorizer.requestResource'. Example: \"object.x must be less than max (\"+string(params.max)+\")\"",
        ),
    ] = None
    reason: Annotated[
        Optional[str],
        Field(
            description='Reason represents a machine-readable description of why this validation failed. If this is the first validation in the list to fail, this reason, as well as the corresponding HTTP response code, are used in the HTTP response to the client. The currently supported reasons are: "Unauthorized", "Forbidden", "Invalid", "RequestEntityTooLarge". If not set, StatusReasonInvalid is used in the response to the client.'
        ),
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
        Optional[apimachinery.LabelSelector],
        Field(
            alias="namespaceSelector",
            description='NamespaceSelector decides whether to run the admission control policy on an object based on whether the namespace for that object matches the selector. If the object itself is a namespace, the matching is performed on object.metadata.labels. If the object is another cluster scoped resource, it never skips the policy.\n\nFor example, to run the webhook on any objects whose namespace is not associated with "runlevel" of "0" or "1";  you will set the selector as follows: "namespaceSelector": {\n  "matchExpressions": [\n    {\n      "key": "runlevel",\n      "operator": "NotIn",\n      "values": [\n        "0",\n        "1"\n      ]\n    }\n  ]\n}\n\nIf instead you want to only run the policy on any objects whose namespace is associated with the "environment" of "prod" or "staging"; you will set the selector as follows: "namespaceSelector": {\n  "matchExpressions": [\n    {\n      "key": "environment",\n      "operator": "In",\n      "values": [\n        "prod",\n        "staging"\n      ]\n    }\n  ]\n}\n\nSee https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/ for more examples of label selectors.\n\nDefault to the empty LabelSelector, which matches everything.',
        ),
    ] = None
    object_selector: Annotated[
        Optional[apimachinery.LabelSelector],
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
        Optional[apimachinery.LabelSelector],
        Field(
            description="selector can be used to match multiple param objects based on their labels. Supply selector: {} to match all resources of the ParamKind.\n\nIf multiple params are found, they are all evaluated with the policy expressions and the results are ANDed together.\n\nOne of `name` or `selector` must be set, but `name` and `selector` are mutually exclusive properties. If one is set, the other must be unset."
        ),
    ] = None


class ValidatingAdmissionPolicyBindingSpec(BaseModel):
    match_resources: Annotated[
        Optional[MatchResources],
        Field(
            alias="matchResources",
            description="MatchResources declares what resources match this binding and will be validated by it. Note that this is intersected with the policy's matchConstraints, so only requests that are matched by the policy can be selected by this. If this is unset, all resources matched by the policy are validated by this binding When resourceRules is unset, it does not constrain resource matching. If a resource is matched by the other fields of this object, it will be validated. Note that this is differs from ValidatingAdmissionPolicy matchConstraints, where resourceRules are required.",
        ),
    ] = None
    param_ref: Annotated[
        Optional[ParamRef],
        Field(
            alias="paramRef",
            description="paramRef specifies the parameter resource used to configure the admission control policy. It should point to a resource of the type specified in ParamKind of the bound ValidatingAdmissionPolicy. If the policy specifies a ParamKind and the resource referred to by ParamRef does not exist, this binding is considered mis-configured and the FailurePolicy of the ValidatingAdmissionPolicy applied. If the policy does not specify a ParamKind then this field is ignored, and the rules are evaluated without a param.",
        ),
    ] = None
    policy_name: Annotated[
        Optional[str],
        Field(
            alias="policyName",
            description="PolicyName references a ValidatingAdmissionPolicy name which the ValidatingAdmissionPolicyBinding binds to. If the referenced resource does not exist, this binding is considered invalid and will be ignored Required.",
        ),
    ] = None
    validation_actions: Annotated[
        Optional[List[str]],
        Field(
            alias="validationActions",
            description='validationActions declares how Validations of the referenced ValidatingAdmissionPolicy are enforced. If a validation evaluates to false it is always enforced according to these actions.\n\nFailures defined by the ValidatingAdmissionPolicy\'s FailurePolicy are enforced according to these actions only if the FailurePolicy is set to Fail, otherwise the failures are ignored. This includes compilation errors, runtime errors and misconfigurations of the policy.\n\nvalidationActions is declared as a set of action values. Order does not matter. validationActions may not contain duplicates of the same action.\n\nThe supported actions values are:\n\n"Deny" specifies that a validation failure results in a denied request.\n\n"Warn" specifies that a validation failure is reported to the request client in HTTP Warning headers, with a warning code of 299. Warnings can be sent both for allowed or denied admission responses.\n\n"Audit" specifies that a validation failure is included in the published audit event for the request. The audit event will contain a `validation.policy.admission.k8s.io/validation_failure` audit annotation with a value containing the details of the validation failures, formatted as a JSON list of objects, each with the following fields: - message: The validation failure message string - policy: The resource name of the ValidatingAdmissionPolicy - binding: The resource name of the ValidatingAdmissionPolicyBinding - expressionIndex: The index of the failed validations in the ValidatingAdmissionPolicy - validationActions: The enforcement actions enacted for the validation failure Example audit annotation: `"validation.policy.admission.k8s.io/validation_failure": "[{"message": "Invalid value", {"policy": "policy.example.com", {"binding": "policybinding.example.com", {"expressionIndex": "1", {"validationActions": ["Audit"]}]"`\n\nClients should expect to handle additional values by ignoring any values not recognized.\n\n"Deny" and "Warn" may not be used together since this combination needlessly duplicates the validation failure both in the API response body and the HTTP warning headers.\n\nRequired.',
        ),
    ] = None


class ValidatingAdmissionPolicySpec(BaseModel):
    audit_annotations: Annotated[
        Optional[List[AuditAnnotation]],
        Field(
            alias="auditAnnotations",
            description="auditAnnotations contains CEL expressions which are used to produce audit annotations for the audit event of the API request. validations and auditAnnotations may not both be empty; a least one of validations or auditAnnotations is required.",
        ),
    ] = None
    failure_policy: Annotated[
        Optional[str],
        Field(
            alias="failurePolicy",
            description="failurePolicy defines how to handle failures for the admission policy. Failures can occur from CEL expression parse errors, type check errors, runtime errors and invalid or mis-configured policy definitions or bindings.\n\nA policy is invalid if spec.paramKind refers to a non-existent Kind. A binding is invalid if spec.paramRef.name refers to a non-existent resource.\n\nfailurePolicy does not define how validations that evaluate to false are handled.\n\nWhen failurePolicy is set to Fail, ValidatingAdmissionPolicyBinding validationActions define how failures are enforced.\n\nAllowed values are Ignore or Fail. Defaults to Fail.",
        ),
    ] = None
    match_conditions: Annotated[
        Optional[List[MatchCondition]],
        Field(
            alias="matchConditions",
            description="MatchConditions is a list of conditions that must be met for a request to be validated. Match conditions filter requests that have already been matched by the rules, namespaceSelector, and objectSelector. An empty list of matchConditions matches all requests. There are a maximum of 64 match conditions allowed.\n\nIf a parameter object is provided, it can be accessed via the `params` handle in the same manner as validation expressions.\n\nThe exact matching logic is (in order):\n  1. If ANY matchCondition evaluates to FALSE, the policy is skipped.\n  2. If ALL matchConditions evaluate to TRUE, the policy is evaluated.\n  3. If any matchCondition evaluates to an error (but none are FALSE):\n     - If failurePolicy=Fail, reject the request\n     - If failurePolicy=Ignore, the policy is skipped",
        ),
    ] = None
    match_constraints: Annotated[
        Optional[MatchResources],
        Field(
            alias="matchConstraints",
            description="MatchConstraints specifies what resources this policy is designed to validate. The AdmissionPolicy cares about a request if it matches _all_ Constraints. However, in order to prevent clusters from being put into an unstable state that cannot be recovered from via the API ValidatingAdmissionPolicy cannot match ValidatingAdmissionPolicy and ValidatingAdmissionPolicyBinding. Required.",
        ),
    ] = None
    param_kind: Annotated[
        Optional[ParamKind],
        Field(
            alias="paramKind",
            description="ParamKind specifies the kind of resources used to parameterize this policy. If absent, there are no parameters for this policy and the param CEL variable will not be provided to validation expressions. If ParamKind refers to a non-existent kind, this policy definition is mis-configured and the FailurePolicy is applied. If paramKind is specified but paramRef is unset in ValidatingAdmissionPolicyBinding, the params variable will be null.",
        ),
    ] = None
    validations: Annotated[
        Optional[List[Validation]],
        Field(
            description="Validations contain CEL expressions which is used to apply the validation. Validations and AuditAnnotations may not both be empty; a minimum of one Validations or AuditAnnotations is required."
        ),
    ] = None
    variables: Annotated[
        Optional[List[Variable]],
        Field(
            description="Variables contain definitions of variables that can be used in composition of other expressions. Each variable is defined as a named CEL expression. The variables defined here will be available under `variables` in other expressions of the policy except MatchConditions because MatchConditions are evaluated before the rest of the policy.\n\nThe expression of a variable can refer to other variables defined earlier in the list but not those after. Thus, Variables must be sorted by the order of first appearance and acyclic."
        ),
    ] = None


class ValidatingAdmissionPolicyStatus(BaseModel):
    conditions: Annotated[
        Optional[List[apimachinery.Condition]],
        Field(
            description="The conditions represent the latest available observations of a policy's current state."
        ),
    ] = None
    observed_generation: Annotated[
        Optional[int],
        Field(
            alias="observedGeneration",
            description="The generation observed by the controller.",
        ),
    ] = None
    type_checking: Annotated[
        Optional[TypeChecking],
        Field(
            alias="typeChecking",
            description="The results of type checking for each expression. Presence of this field indicates the completion of the type checking.",
        ),
    ] = None


class ValidatingAdmissionPolicy(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["ValidatingAdmissionPolicy"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ValidatingAdmissionPolicy"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="Standard object metadata; More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata."
        ),
    ] = None
    spec: Annotated[
        Optional[ValidatingAdmissionPolicySpec],
        Field(
            description="Specification of the desired behavior of the ValidatingAdmissionPolicy."
        ),
    ] = None
    status: Annotated[
        Optional[ValidatingAdmissionPolicyStatus],
        Field(
            description="The status of the ValidatingAdmissionPolicy, including warnings that are useful to determine if the policy behaves in the expected way. Populated by the system. Read-only."
        ),
    ] = None


class ValidatingAdmissionPolicyBinding(Resource):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    kind: Annotated[
        Optional[Literal["ValidatingAdmissionPolicyBinding"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ValidatingAdmissionPolicyBinding"
    metadata: Annotated[
        Optional[apimachinery.ObjectMeta],
        Field(
            description="Standard object metadata; More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#metadata."
        ),
    ] = None
    spec: Annotated[
        Optional[ValidatingAdmissionPolicyBindingSpec],
        Field(
            description="Specification of the desired behavior of the ValidatingAdmissionPolicyBinding."
        ),
    ] = None


class ValidatingAdmissionPolicyBindingList(ResourceList):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    items: Annotated[
        List[ValidatingAdmissionPolicyBinding],
        Field(description="List of PolicyBinding."),
    ]
    kind: Annotated[
        Optional[Literal["ValidatingAdmissionPolicyBindingList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ValidatingAdmissionPolicyBindingList"
    metadata: Annotated[
        Optional[apimachinery.ListMeta],
        Field(
            description="Standard list metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = None


class ValidatingAdmissionPolicyList(ResourceList):
    api_version: Annotated[
        Optional[Literal["admissionregistration.k8s.io/v1alpha1"]],
        Field(
            alias="apiVersion",
            description="APIVersion defines the versioned schema of this representation of an object. Servers should convert recognized schemas to the latest internal value, and may reject unrecognized values. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources",
        ),
    ] = "admissionregistration.k8s.io/v1alpha1"
    items: Annotated[
        List[ValidatingAdmissionPolicy],
        Field(description="List of ValidatingAdmissionPolicy."),
    ]
    kind: Annotated[
        Optional[Literal["ValidatingAdmissionPolicyList"]],
        Field(
            description="Kind is a string value representing the REST resource this object represents. Servers may infer this from the endpoint the client submits requests to. Cannot be updated. In CamelCase. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = "ValidatingAdmissionPolicyList"
    metadata: Annotated[
        Optional[apimachinery.ListMeta],
        Field(
            description="Standard list metadata. More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds"
        ),
    ] = None