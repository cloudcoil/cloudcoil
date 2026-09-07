# API reference

Use the [guides](index.md) for workflows and examples. This reference follows the
public import paths used by applications.

## Resources and clients

::: cloudcoil.resources
    options:
      members: [Resource, ResourceList, Unstructured, get_model, parse, parse_file]

::: cloudcoil.client
    options:
      members: [Config, APIClient, AsyncAPIClient]

## Controllers

::: cloudcoil.controller
    options:
      members: [Controller, Request, ResourceKey, Result, TerminalError, mutate, ensure_finalizer, remove_finalizer]

## Operators

::: cloudcoil.operator
    options:
      members: [Operator, RBACRule, WebhookServer]

## Custom resources

::: cloudcoil.crd
    options:
      members: [custom_resource, CRD, PrinterColumn, CEL, ListType, SchemaError]

## Admission

::: cloudcoil.admission
    options:
      members: [AdmissionWebhook, AdmissionRequest, AdmissionDenied, UserInfo, mutating, validating]

## Caching and runtime

::: cloudcoil.caching
    options:
      members: [Cache, CachedResources, AsyncInformer, SyncInformer]

::: cloudcoil.controller.Manager

::: cloudcoil.controller.LeaderElection

::: cloudcoil.controller.HealthServer

::: cloudcoil.controller.ControllerStatus

::: cloudcoil.controller.WorkQueue
