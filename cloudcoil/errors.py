class APIError(Exception):
    pass


class ResourceNotFound(APIError):
    pass


class ResourceConflict(APIError):
    pass


class WatchError(APIError):
    pass


class WaitTimeout(APIError):
    pass
