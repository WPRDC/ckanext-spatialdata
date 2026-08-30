# encoding: utf-8
# Types and Constants used throughout extension.
from enum import Enum
from typing import Callable, TypedDict, Literal, Union

GEOMETRY_TYPES = {
    "POINT",
    "LINESTRING",
    "POLYGON",
    "MULTIPOINT",
    "MULTILINESTRING",
    "MULTIPOLYGON",
}


class GeoreferenceStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETE = "COMPLETE"
    WORKING = "WORKING"
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    ERROR = "ERROR"


StatusCallback = Callable[[str, Union[str, None], Union[str, None]], None]

SpecificStatusCallback = Callable[[Union[str, None], Union[str, None]], None]


class HookDataDict(TypedDict):
    resource_id: str
    status: str
    job_created: str
    value: Union[dict, None]
    error: Union[str, None]


class StatusDict(TypedDict):
    job_id: str
    status: str
    last_updated: str
    rows_completed: Union[int, None]
    notes: Union[str, None]


StatusResult = StatusDict | dict[Literal["status"] : str]
