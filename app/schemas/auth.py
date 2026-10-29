from typing import Literal

from app.schemas.base import CamelModel

roles = Literal["LANDLORD", "TENANT"]


class SyncUser(CamelModel):
    role: roles | None
