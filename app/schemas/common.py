from app.schemas.base import CamelModel


class Pagination(CamelModel):
    page: int
    limit: int
    total: int
    total_pages: int
    has_next_page: bool
    has_previous_page: bool


class MessageResponse(CamelModel):
    message: str


class HealthResponse(CamelModel):
    status: str
    timestamp: str
