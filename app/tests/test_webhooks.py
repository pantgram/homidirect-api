import uuid

from app.tests.conftest import API, _clerk_user_registry, create_db_user, make_test_token


def _user_event(event_type: str, clerk_user_id: str, email: str | None = None, **overrides) -> dict:
    data = {
        "id": clerk_user_id,
        "first_name": "Web",
        "last_name": "Hook",
        "email_addresses": [{"id": "idn_primary", "email_address": email}],
        "primary_email_address_id": "idn_primary",
    }
    data.update(overrides)
    return {"data": data, "type": event_type}


async def _post_webhook(client, event: dict):
    return await client.post(f"{API}/webhooks/clerk", json=event)


class TestWebhookAuth:
    async def test_invalid_signature_rejected(self, client, monkeypatch):
        """Fail-closed: a payload failing verification must never be processed."""
        from svix.webhooks import WebhookVerificationError

        from app.api.v1 import webhooks as webhooks_api

        def _failing_verify(payload, headers):
            raise WebhookVerificationError

        monkeypatch.setattr(webhooks_api, "verify_webhook", _failing_verify)

        response = await _post_webhook(client, _user_event("user.created", f"user_{uuid.uuid4().hex}"))

        assert response.status_code == 400

    async def test_endpoint_requires_no_bearer(self, client):
        """Webhook authenticates via the Svix signature, not a bearer token."""
        response = await _post_webhook(
            client, _user_event("user.created", f"user_{uuid.uuid4().hex}", email="no-bearer@example.com")
        )

        assert response.status_code == 200


class TestUserCreated:
    async def test_created_upserts_profile_with_tenant_default(self, client):
        clerk_user_id = f"user_{uuid.uuid4().hex}"

        response = await _post_webhook(client, _user_event("user.created", clerk_user_id, email="created@example.com"))

        assert response.status_code == 200
        token = make_test_token(clerk_user_id, "created@example.com")
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == "created@example.com"
        assert body["firstName"] == "Web"
        assert body["lastName"] == "Hook"
        assert body["role"] == "TENANT"

    async def test_created_is_idempotent(self, client):
        clerk_user_id = f"user_{uuid.uuid4().hex}"
        event = _user_event("user.created", clerk_user_id, email="idem-hook@example.com")
        await _post_webhook(client, event)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        token = make_test_token(clerk_user_id, "idem-hook@example.com")
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200

    async def test_created_with_conflicting_email_still_200(self, client, session):
        """Email collision must never 4xx: Clerk retries non-2xx deliveries."""
        await create_db_user(session, email="taken-hook@example.com")

        response = await _post_webhook(
            client, _user_event("user.created", f"user_{uuid.uuid4().hex}", email="taken-hook@example.com")
        )

        assert response.status_code == 200

    async def test_created_without_email_is_ignored(self, client):
        """email is NOT NULL on users; a delivery without a resolvable email is
        logged and 200'd rather than answered 4xx (Clerk retries non-2xx)."""
        clerk_user_id = f"user_{uuid.uuid4().hex}"

        response = await _post_webhook(client, _user_event("user.created", clerk_user_id, email=None))

        assert response.status_code == 200
        token = make_test_token(clerk_user_id, "never-created@example.com")
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 401

    async def test_created_applies_real_role_via_sync_afterwards(self, client):
        """The webhook safety-net creates TENANT; sync immediately applies the real role."""
        clerk_user_id = f"user_{uuid.uuid4().hex}"
        _clerk_user_registry[clerk_user_id] = {
            "email": "sync-after@example.com",
            "first_name": "Sync",
            "last_name": "After",
        }
        await _post_webhook(client, _user_event("user.created", clerk_user_id, email="sync-after@example.com"))

        token = make_test_token(clerk_user_id, "sync-after@example.com")
        response = await client.post(
            f"{API}/auth/sync", json={"role": "LANDLORD"}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "LANDLORD"


class TestUserUpdated:
    async def test_updated_refreshes_names_and_email(self, client, tenant):
        clerk_user_id = tenant["sub"]

        response = await _post_webhook(
            client,
            _user_event(
                "user.updated",
                clerk_user_id,
                email="renamed@example.com",
                first_name="Renamed",
                last_name="Person",
            ),
        )

        assert response.status_code == 200
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tenant['token']}"})
        assert me.status_code == 200
        body = me.json()
        assert body["firstName"] == "Renamed"
        assert body["lastName"] == "Person"
        assert body["email"] == "renamed@example.com"

    async def test_updated_never_touches_role(self, client, tenant):
        clerk_user_id = tenant["sub"]

        response = await _post_webhook(
            client,
            _user_event(
                "user.updated",
                clerk_user_id,
                email=tenant["email"],
                first_name="Still",
                last_name="Tenant",
            ),
        )

        assert response.status_code == 200
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tenant['token']}"})
        assert me.json()["role"] == "TENANT"

    async def test_updated_unknown_user_ignored(self, client):
        response = await _post_webhook(
            client, _user_event("user.updated", f"user_{uuid.uuid4().hex}", email="unknown@example.com")
        )

        assert response.status_code == 200

    async def test_updated_is_idempotent(self, client, tenant):
        event = _user_event(
            "user.updated", tenant["sub"], email="twice@example.com", first_name="Twice", last_name="Updated"
        )
        await _post_webhook(client, event)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tenant['token']}"})
        assert me.json()["email"] == "twice@example.com"


class TestUserDeleted:
    async def test_deleted_removes_local_row(self, client, tenant):
        response = await _post_webhook(client, {"data": {"id": tenant["sub"], "deleted": True}, "type": "user.deleted"})

        assert response.status_code == 200
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tenant['token']}"})
        assert me.status_code == 401

    async def test_deleted_is_idempotent(self, client, tenant):
        await _post_webhook(client, {"data": {"id": tenant["sub"], "deleted": True}, "type": "user.deleted"})

        response = await _post_webhook(client, {"data": {"id": tenant["sub"], "deleted": True}, "type": "user.deleted"})

        assert response.status_code == 200

    async def test_deleted_unknown_user_ignored(self, client):
        response = await _post_webhook(client, {"data": {"id": f"user_{uuid.uuid4().hex}"}, "type": "user.deleted"})

        assert response.status_code == 200

    async def test_delete_endpoint_then_webhook_is_noop(self, client, tenant, tenant_headers):
        """DELETE /users/{id} deletes locally + in Clerk; the resulting webhook is a no-op."""
        delete = await client.delete(f"{API}/users/{tenant['user']['id']}", headers=tenant_headers)
        assert delete.status_code == 204

        response = await _post_webhook(client, {"data": {"id": tenant["sub"], "deleted": True}, "type": "user.deleted"})

        assert response.status_code == 200


class TestOtherEvents:
    async def test_unknown_event_type_ignored(self, client, tenant):
        response = await _post_webhook(client, {"data": {"id": tenant["sub"]}, "type": "session.ended"})

        assert response.status_code == 200
        me = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {tenant['token']}"})
        assert me.status_code == 200
