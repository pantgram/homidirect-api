import uuid

import jwt as pyjwt
import pytest

from app.tests.conftest import (
    API,
    TEST_AUTH_SECRET,
    auth_headers_for,
    create_db_user,
    headers_from_tokens,
    make_test_token,
    sync_user,
)


class TestSync:
    async def test_sync_creates_profile(self, client):
        data = await sync_user(client, email="new@example.com", role="LANDLORD", first_name="New", last_name="User")

        body = data["user"]
        assert body["email"] == "new@example.com"
        assert body["firstName"] == "New"
        assert body["lastName"] == "User"
        assert body["role"] == "LANDLORD"
        assert body["id"] > 0
        assert body["createdAt"]

    async def test_sync_is_idempotent(self, client):
        sub = str(uuid.uuid4())
        first = await sync_user(client, email="idem@example.com", sub=sub)
        second = await sync_user(client, email="idem@example.com", sub=sub)

        assert second["user"]["id"] == first["user"]["id"]

    async def test_sync_updates_existing_profile(self, client, session):
        data = await sync_user(client, email="update@example.com", role="TENANT")
        updated = await sync_user(
            client, email="update@example.com", role="LANDLORD", first_name="Renamed", sub=data["sub"]
        )

        assert updated["user"]["id"] == data["user"]["id"]
        assert updated["user"]["firstName"] == "Renamed"
        assert updated["user"]["role"] == "LANDLORD"

    async def test_sync_updates_names_and_email_from_claims(self, client):
        """After supabase.auth.updateUser the new claims overwrite the stored profile."""
        data = await sync_user(client, email="before@example.com", first_name="Old", last_name="Name")
        token = make_test_token(
            data["sub"],
            "after@example.com",
            user_metadata={"first_name": "New", "last_name": "Name"},
        )

        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        body = response.json()["user"]
        assert body["id"] == data["user"]["id"]
        assert body["firstName"] == "New"
        assert body["lastName"] == "Name"
        assert body["email"] == "after@example.com"

    @pytest.mark.parametrize("role", ["LANDLORD", "TENANT", "BOTH"])
    async def test_sync_copies_allowlisted_role(self, client, role):
        data = await sync_user(client, email=f"{role.lower()}-copy@example.com", role=role)

        assert data["user"]["role"] == role

    async def test_sync_ignores_admin_role_in_metadata(self, client):
        """ADMIN can never come from client-writable user_metadata."""
        data = await sync_user(client, email="no-admin@example.com", role="TENANT")
        token = make_test_token(
            data["sub"],
            "no-admin@example.com",
            user_metadata={"first_name": "Test", "last_name": "User", "role": "ADMIN"},
        )

        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "TENANT"

    async def test_sync_ignores_invalid_role_in_metadata(self, client):
        data = await sync_user(client, email="bad-role@example.com", role="LANDLORD")
        token = make_test_token(
            data["sub"],
            "bad-role@example.com",
            user_metadata={"first_name": "Test", "last_name": "User", "role": "SUPERUSER"},
        )

        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "LANDLORD"

        # On create, an invalid metadata role falls back to the TENANT default.
        create_token = make_test_token(
            str(uuid.uuid4()),
            "default-role@example.com",
            user_metadata={"first_name": "New", "last_name": "User", "role": "SUPERUSER"},
        )
        created = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {create_token}"})
        assert created.json()["user"]["role"] == "TENANT"

    async def test_sync_conflicting_email(self, client, session):
        await create_db_user(session, email="taken@example.com")

        token = make_test_token(str(uuid.uuid4()), "taken@example.com")
        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 409
        assert response.json() == {"error": "ConflictError", "message": "Email already registered"}

    async def test_sync_requires_authentication(self, client):
        response = await client.post(f"{API}/auth/sync")

        assert response.status_code == 401

    async def test_sync_rejects_tampered_token(self, client):
        token = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "email": "tamper@example.com", "role": "authenticated"},
            "wrong-secret-that-is-long-enough-for-hs256",
            algorithm="HS256",
        )
        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    async def test_sync_rejects_missing_email_claim(self, client):
        token = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "role": "authenticated"}, TEST_AUTH_SECRET, algorithm="HS256"
        )
        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401


class TestCurrentUserAuth:
    async def test_access_token_without_header(self, client):
        response = await client.get(f"{API}/users/me")

        assert response.status_code == 401

    async def test_access_token_malformed(self, client):
        response = await client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 401

    async def test_anonymous_role_rejected(self, client):
        token = make_test_token(str(uuid.uuid4()), "anon@example.com", role="anonymous")

        response = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    async def test_unknown_supabase_user(self, client):
        token = make_test_token(str(uuid.uuid4()), "ghost@example.com")

        response = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert response.json()["message"] == "Unauthorized"

    async def test_anonymous_role_treated_as_unauthenticated_for_optional_user(self, client):
        token = make_test_token(str(uuid.uuid4()), "anon-search@example.com", role="anonymous")

        response = await client.get(
            f"{API}/listings/search", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200

    async def test_banned_user_forbidden(self, client, session):
        user = await create_db_user(session, email="banned@example.com", status="ACTIVE")
        user.status = "BANNED"
        await session.commit()

        response = await client.get(f"{API}/users/me", headers=auth_headers_for(user))

        assert response.status_code == 403
        assert "banned" in response.json()["message"]

    async def test_suspended_user_forbidden(self, client, session):
        user = await create_db_user(session, email="suspended@example.com", status="ACTIVE")
        user.status = "SUSPENDED"
        await session.commit()

        response = await client.get(f"{API}/users/me", headers=auth_headers_for(user))

        assert response.status_code == 403

    async def test_db_user_maps_via_supabase_id(self, client, session):
        sub = str(uuid.uuid4())
        user = await create_db_user(session, email="mapped@example.com", role="TENANT")
        user.supabase_user_id = uuid.UUID(sub)
        await session.commit()

        response = await client.get(f"{API}/users/me", headers=headers_from_tokens(
            {"token": make_test_token(sub, user.email)}
        ))

        assert response.status_code == 200
        assert response.json()["email"] == "mapped@example.com"
