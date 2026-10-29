import uuid

import jwt as pyjwt
import pytest

from app.tests.conftest import (
    API,
    _clerk_user_registry,
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
        sub = f"user_{uuid.uuid4().hex}"
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

    async def test_sync_updates_names_and_email_from_backend_api(self, client):
        """After a Clerk profile update the Backend API data overwrites the stored profile."""
        data = await sync_user(client, email="before@example.com", first_name="Old", last_name="Name")
        _clerk_user_registry[data["sub"]] = {
            "email": "after@example.com",
            "first_name": "New",
            "last_name": "Name",
        }

        response = await client.post(
            f"{API}/auth/sync", json={"role": None}, headers={"Authorization": f"Bearer {data['token']}"}
        )

        assert response.status_code == 200
        body = response.json()["user"]
        assert body["id"] == data["user"]["id"]
        assert body["firstName"] == "New"
        assert body["lastName"] == "Name"
        assert body["email"] == "after@example.com"

    @pytest.mark.parametrize("role", ["LANDLORD", "TENANT"])
    async def test_sync_applies_body_role(self, client, role):
        data = await sync_user(client, email=f"{role.lower()}-copy@example.com", role=role)

        assert data["user"]["role"] == role

    @pytest.mark.parametrize("role", ["BOTH", "ADMIN", "SUPERUSER"])
    async def test_sync_rejects_unassignable_body_role(self, client, role):
        """BOTH and ADMIN exist in the app but can never be self-assigned via /auth/sync."""
        token = make_test_token(f"user_{uuid.uuid4().hex}", f"{role.lower()}-rejected@example.com")

        response = await client.post(
            f"{API}/auth/sync", json={"role": role}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 422

    async def test_sync_defaults_to_tenant_without_body_role(self, client):
        sub = f"user_{uuid.uuid4().hex}"
        _clerk_user_registry[sub] = {"email": "default-role@example.com", "first_name": None, "last_name": None}
        token = make_test_token(sub, "default-role@example.com")

        response = await client.post(
            f"{API}/auth/sync", json={"role": None}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "TENANT"

    async def test_sync_requires_request_body(self, client):
        token = make_test_token(f"user_{uuid.uuid4().hex}", "no-body@example.com")

        response = await client.post(f"{API}/auth/sync", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 422

    async def test_sync_keeps_stored_role_when_body_role_missing(self, client):
        data = await sync_user(client, email="keep-role@example.com", role="LANDLORD")

        response = await client.post(
            f"{API}/auth/sync", json={"role": None}, headers={"Authorization": f"Bearer {data['token']}"}
        )

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "LANDLORD"

    async def test_sync_ignores_role_in_clerk_profile(self, client):
        """Role comes from the body only; an ADMIN role attached to the Clerk
        Backend API profile can never be applied by sync."""
        sub = f"user_{uuid.uuid4().hex}"
        _clerk_user_registry[sub] = {
            "email": "metadata-role@example.com",
            "first_name": "Test",
            "last_name": "User",
            "role": "ADMIN",
        }
        token = make_test_token(sub, "metadata-role@example.com")

        response = await client.post(
            f"{API}/auth/sync", json={"role": "LANDLORD"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "LANDLORD"

    async def test_sync_conflicting_email(self, client, session):
        await create_db_user(session, email="taken@example.com")

        sub = f"user_{uuid.uuid4().hex}"
        _clerk_user_registry[sub] = {"email": "taken@example.com", "first_name": None, "last_name": None}
        token = make_test_token(sub, "taken@example.com")
        response = await client.post(
            f"{API}/auth/sync", json={"role": "TENANT"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 409
        assert response.json() == {"error": "ConflictError", "message": "Email already registered"}

    async def test_sync_requires_authentication(self, client):
        response = await client.post(f"{API}/auth/sync", json={"role": "TENANT"})

        assert response.status_code == 401

    async def test_sync_rejects_tampered_token(self, client):
        token = pyjwt.encode(
            {"sub": f"user_{uuid.uuid4().hex}", "email": "tamper@example.com"},
            "wrong-secret-that-is-long-enough-for-hs256",
            algorithm="HS256",
        )
        response = await client.post(
            f"{API}/auth/sync", json={"role": "TENANT"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    async def test_sync_rejects_unknown_clerk_user(self, client):
        """A valid token whose sub has no Clerk Backend API user fails loudly."""
        token = make_test_token(f"user_{uuid.uuid4().hex}", "ghost@example.com")

        response = await client.post(
            f"{API}/auth/sync", json={"role": "TENANT"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 500

    async def test_sync_rejects_profile_without_email(self, client):
        sub = f"user_{uuid.uuid4().hex}"
        _clerk_user_registry[sub] = {"email": None, "first_name": "No", "last_name": "Email"}
        token = make_test_token(sub, "no-email@example.com")

        response = await client.post(
            f"{API}/auth/sync", json={"role": "TENANT"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401


class TestCurrentUserAuth:
    async def test_access_token_without_header(self, client):
        response = await client.get(f"{API}/users/me")

        assert response.status_code == 401

    async def test_access_token_malformed(self, client):
        response = await client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 401

    async def test_unknown_clerk_user(self, client):
        token = make_test_token(f"user_{uuid.uuid4().hex}", "ghost@example.com")

        response = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert response.json()["message"] == "Unauthorized"

    async def test_invalid_token_treated_as_unauthenticated_for_optional_user(self, client):
        token = pyjwt.encode(
            {"sub": f"user_{uuid.uuid4().hex}", "email": "anon-search@example.com"},
            "wrong-secret-that-is-long-enough-for-hs256",
            algorithm="HS256",
        )

        response = await client.get(f"{API}/listings/search", headers={"Authorization": f"Bearer {token}"})

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

    async def test_db_user_maps_via_clerk_id(self, client, session):
        sub = f"user_{uuid.uuid4().hex}"
        user = await create_db_user(session, email="mapped@example.com", role="TENANT")
        user.clerk_user_id = sub
        await session.commit()

        response = await client.get(
            f"{API}/users/me", headers=headers_from_tokens({"token": make_test_token(sub, user.email)})
        )

        assert response.status_code == 200
        assert response.json()["email"] == "mapped@example.com"
