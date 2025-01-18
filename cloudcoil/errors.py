class APIError(Exception):
    pass


class ResourceNotFound(APIError):
    pass


class ResourceAlreadyExists(APIError):
    pass


class WatchError(APIError):
    pass


class WaitTimeout(APIError):
    pass
