class LedgerError(Exception):
    status_code = 400


class NotFound(LedgerError):
    status_code = 404


class Conflict(LedgerError):
    status_code = 409


class InsufficientFunds(LedgerError):
    status_code = 422

