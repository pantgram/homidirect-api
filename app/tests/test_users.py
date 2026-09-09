from app.tests.conftest import API, headers_from_tokens


class TestMe:
    async def test_me_returns_profile(self, client, tenant):
        response = await client.get(f"{API}/users/me", headers=headers_from_tokens(tenant["token"]))

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "tenant@example.com"
        assert body["firstName"] == "Test"
        assert body["role"] == "TENANT"
        assert body["createdAt"]


class TestGetUser:
    async def test_get_user_by_id(self, client, tenant, tenant_headers):
        response = await client.get(f"{API}/users/{tenant['user']['id']}", headers=tenant_headers)

        assert response.status_code == 200
        assert response.json()["user"]["email"] == "tenant@example.com"

    async def test_get_unknown_user(self, client, tenant_headers):
        response = await client.get(f"{API}/users/999999", headers=tenant_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "User not found"

    async def test_requires_authentication(self, client):
        response = await client.get(f"{API}/users/1")

        assert response.status_code == 401


class TestUpdateUser:
    async def test_update_own_profile(self, client, tenant, tenant_headers):
        response = await client.patch(
            f"{API}/users/{tenant['user']['id']}",
            json={"firstName": "Updated", "lastName": "Name"},
            headers=tenant_headers,
        )

        assert response.status_code == 200
        body = response.json()["user"]
        assert body["firstName"] == "Updated"
        assert body["lastName"] == "Name"
        assert body["email"] == "tenant@example.com"

    async def test_cannot_update_other_user(self, client, tenant, landlord, tenant_headers):
        response = await client.patch(
            f"{API}/users/{landlord['user']['id']}",
            json={"firstName": "Hacker"},
            headers=tenant_headers,
        )

        assert response.status_code == 404
        assert response.json()["message"] == "User not found"

    async def test_email_cannot_be_changed_via_update(self, client, tenant, landlord, tenant_headers):
        response = await client.patch(
            f"{API}/users/{tenant['user']['id']}",
            json={"email": landlord["user"]["email"]},
            headers=tenant_headers,
        )

        assert response.status_code == 200
        assert response.json()["user"]["email"] == "tenant@example.com"

    async def test_update_unknown_user(self, client, tenant_headers):
        response = await client.patch(
            f"{API}/users/999999", json={"firstName": "Ghost"}, headers=tenant_headers
        )

        assert response.status_code == 404

    async def test_update_invalid_role(self, client, tenant, tenant_headers):
        response = await client.patch(
            f"{API}/users/{tenant['user']['id']}", json={"role": "ADMIN"}, headers=tenant_headers
        )

        assert response.status_code == 422


class TestDeleteUser:
    async def test_delete_own_account(self, client, tenant, tenant_headers):
        response = await client.delete(f"{API}/users/{tenant['user']['id']}", headers=tenant_headers)

        assert response.status_code == 204

    async def test_login_after_account_deletion(self, client, tenant, tenant_headers):
        await client.delete(f"{API}/users/{tenant['user']['id']}", headers=tenant_headers)
        login = await client.post(f"{API}/auth/login", json={"email": "tenant@example.com", "password": "Password123"})

        assert login.status_code == 401

    async def test_cannot_delete_other_user(self, client, landlord, tenant_headers):
        response = await client.delete(
            f"{API}/users/{landlord['user']['id']}", headers=tenant_headers
        )

        assert response.status_code == 404

    async def test_delete_unknown_user(self, client, tenant_headers):
        response = await client.delete(f"{API}/users/999999", headers=tenant_headers)

        assert response.status_code == 404


class TestFavorites:
    async def test_full_favorite_lifecycle(self, client, listing, tenant_headers):
        listing_id = listing["id"]

        add = await client.post(f"{API}/favorites/{listing_id}", headers=tenant_headers)
        assert add.status_code == 200
        assert add.json() == {"success": True, "added": True, "message": "Favorite added"}

        add_again = await client.post(f"{API}/favorites/{listing_id}", headers=tenant_headers)
        assert add_again.status_code == 200
        assert add_again.json()["added"] is False

        check = await client.get(f"{API}/favorites/{listing_id}/check", headers=tenant_headers)
        assert check.status_code == 200
        assert check.json() == {"isFavorited": True}

        ids = await client.get(f"{API}/favorites/ids", headers=tenant_headers)
        assert ids.status_code == 200
        assert ids.json() == {"favoriteIds": [listing_id]}

        favorites = await client.get(f"{API}/favorites/", headers=tenant_headers)
        assert favorites.status_code == 200
        body = favorites.json()
        assert body["pagination"]["total"] == 1
        assert body["data"][0]["id"] == listing_id
        assert body["data"][0]["primaryImage"] is None

        remove = await client.delete(f"{API}/favorites/{listing_id}", headers=tenant_headers)
        assert remove.status_code == 200
        assert remove.json() == {"removed": True}

        check_after = await client.get(f"{API}/favorites/{listing_id}/check", headers=tenant_headers)
        assert check_after.json() == {"isFavorited": False}

    async def test_add_favorite_unknown_listing(self, client, tenant_headers):
        response = await client.post(f"{API}/favorites/999999", headers=tenant_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Listing not found"

    async def test_remove_nonexistent_favorite(self, client, listing, tenant_headers):
        response = await client.delete(f"{API}/favorites/{listing['id']}", headers=tenant_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Favorite not found"

    async def test_favorites_require_authentication(self, client, listing):
        response = await client.post(f"{API}/favorites/{listing['id']}")

        assert response.status_code == 401

    async def test_other_user_favorites_are_isolated(self, client, listing, tenant_headers, landlord_headers):
        await client.post(f"{API}/favorites/{listing['id']}", headers=tenant_headers)

        ids = await client.get(f"{API}/favorites/ids", headers=landlord_headers)

        assert ids.json() == {"favoriteIds": []}
