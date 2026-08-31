import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException

from app.api.v1 import router
from app.config.database import engine
from app.config.limiter import limiter
from app.config.settings import settings
from app.middleware.camel_case import CamelCaseMiddleware
from app.utils.errors import (
    AppError,
    app_error_handler,
    generic_error_handler,
    http_exception_handler,
    validation_error_handler,
)

logger = logging.getLogger("homidirect")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


openapi_tags = [
    {"name": "Health", "description": "Service health checks"},
    {"name": "Auth", "description": "Registration, login, tokens, and password management"},
    {"name": "Google Auth", "description": "Google OAuth 2.0 login flow"},
    {"name": "Users", "description": "User profile management"},
    {"name": "Listings", "description": "Property listing CRUD, search, and contact"},
    {"name": "Listing Images", "description": "Image uploads attached to existing listings"},
    {"name": "Verification", "description": "Listing verification documents, status, and history"},
    {"name": "Admin Verification", "description": "Admin review of listing verifications"},
    {"name": "Favorites", "description": "Saved listings"},
    {"name": "Bookings", "description": "Listing visit bookings"},
    {"name": "Availability Slots", "description": "Bookable time slots for listings"},
    {"name": "Geocoding", "description": "Address search, autocomplete, and reverse geocoding"},
]

app = FastAPI(title="HomiDirect API", version="1.0.0", lifespan=lifespan, openapi_tags=openapi_tags)
app.include_router(router, prefix="/api")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, generic_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_middleware(CamelCaseMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




