from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    api: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"
    worker: Literal["ok"] = "ok"
