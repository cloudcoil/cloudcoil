class APIError(Exception):
    def __init__(self, detail, *, status_code: int | None = None):
        self.detail = detail
        self.status_code = status_code
        message = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
        super().__init__(message)


class ResourceNotFound(APIError):
    pass


class ResourceConflict(APIError):
    pass


class WatchError(APIError):
    pass


class WaitTimeout(APIError):
    pass


class WatchExpired(WatchError):
    """The watch history expired; a caching consumer must relist."""
