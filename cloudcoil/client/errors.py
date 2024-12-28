class APIError(Exception):
    pass


class ResourceNotFound(APIError):
    pass


class ResourceAlreadyExists(APIError):
    pass
