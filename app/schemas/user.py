from app.schemas.base import CamelModel

# Allowlist for roles that may arrive from Supabase user_metadata during
# profile sync (app/services/auth.py). ADMIN is deliberately not assignable.
VALID_ROLES = {"LANDLORD", "TENANT", "BOTH"}


class UserResponse(CamelModel):
    id: int
    first_name: str
    last_name: str
    email: str
    created_at: str


class UserWithRoleResponse(CamelModel):
    id: int
    first_name: str
    last_name: str
    email: str
    role: str
    created_at: str


class UserIdParam(CamelModel):
    id: int


class UserDetailResponse(CamelModel):
    user: UserWithRoleResponse


class FavoriteIdsResponse(CamelModel):
    favorite_ids: list[int]


class CheckFavoriteResponse(CamelModel):
    is_favorited: bool


class AddFavoriteResponse(CamelModel):
    success: bool
    added: bool
    message: str


class RemoveFavoriteResponse(CamelModel):
    removed: bool
