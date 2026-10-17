class DomainError(Exception):
    """An expected, user-facing failure. Mapped to the API error shape."""

    status_code = 409

    def __init__(self, code: str, message: str, details: dict | None = None, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code


class NotFound(DomainError):
    status_code = 404

    def __init__(self, what: str):
        super().__init__("not_found", f"{what} not found", status_code=404)
