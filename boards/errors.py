"""Domain errors raised by the repository layer."""


class BoardsError(Exception):
    """Base class for errors that are safe to show to the user."""


class ValidationError(BoardsError, ValueError):
    """Invalid input: the request was rejected and nothing was written."""


class NotFoundError(BoardsError, LookupError):
    """The referenced record does not exist (or is in the recycle bin)."""


class ConflictError(BoardsError):
    """Someone else changed the same data since it was loaded."""

    def __init__(self, message: str, fields=()):
        super().__init__(message)
        self.fields = list(fields)
