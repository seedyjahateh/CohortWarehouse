"""Error taxonomy.

The distinction matters operationally (Section 9.3): transient failures may be retried
automatically; contract and quality failures must never be blindly retried.
"""


class CohortWarehouseError(Exception):
    """Base class. `retryable` tells orchestration whether a blind retry is sensible."""

    retryable = False
    exit_code = 1


class ConfigurationError(CohortWarehouseError):
    exit_code = 2


class ContractError(CohortWarehouseError):
    """Source contract or manifest violation: the delivery itself is wrong."""

    exit_code = 3


class ProvenanceError(ContractError):
    """ING-07: batch lacks approved synthetic provenance."""


class QualityGateError(CohortWarehouseError):
    """A blocking quality/reconciliation check failed; publication is refused."""

    exit_code = 4


class BuildError(CohortWarehouseError):
    """A transformation (model/seed) failed. Fix the code or data; do not retry blindly."""

    exit_code = 8


class PublicationError(CohortWarehouseError):
    exit_code = 5


class ConcurrencyError(CohortWarehouseError):
    """Another pipeline process holds the warehouse write lock."""

    retryable = True
    exit_code = 6


class TransientError(CohortWarehouseError):
    retryable = True
    exit_code = 7
