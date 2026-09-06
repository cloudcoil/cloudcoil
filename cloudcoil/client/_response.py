"""Shared Kubernetes HTTP error handling for resource and streaming endpoints."""

import httpx

from cloudcoil.errors import APIError, ResourceConflict, ResourceNotFound


def raise_for_status(response: httpx.Response) -> None:
    """Raise a Cloudcoil error after the response body has been read."""
    if response.is_success:
        return
    try:
        detail = response.json()
    except ValueError:
        detail = response.text or response.reason_phrase
    error = {404: ResourceNotFound, 409: ResourceConflict}.get(response.status_code, APIError)
    raise error(detail, status_code=response.status_code)
