from pydantic import BaseModel

from gc_batch.constants import CustomStrEnum


class JobState(CustomStrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DELETION_IN_PROGRESS = "DELETION_IN_PROGRESS"
    DELETED = "DELETED"
    CANCELLED = "CANCELLED"


class JobResult(BaseModel):
    state: JobState
    output: str = ""
    error: str = ""
