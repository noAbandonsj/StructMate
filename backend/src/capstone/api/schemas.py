from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class Page[T](BaseModel):
    items: list[T]
    page: int
    page_size: int
    total: int
