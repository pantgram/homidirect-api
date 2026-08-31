from app.tests.conftest import API, create_listing, headers_from_tokens


class TestCamelCaseResponses:
    async def test_user_profile_keys_are_camel_case(self, client, tenant):
        response = await client.get(f"{API}/users/me", headers=headers_from_tokens(tenant["token"]))

        body = response.json()
        assert "firstName" in body
        assert "lastName" in body
        assert "createdAt" in body
        assert "first_name" not in body

    async def test_listing_keys_are_camel_case(self, client, listing):
        body = (await client.get(f"{API}/listings/{listing['id']}")).json()["listing"]

        assert "titleEl" in body
        assert "propertyType" in body
        assert "verificationStatus" in body
        assert "isFeatured" in body
        assert "title_el" not in body

    async def test_pagination_keys_are_camel_case(self, client, landlord_headers):
        await create_listing(client, landlord_headers)

        response = await client.get(f"{API}/listings/search")

        pagination = response.json()["pagination"]
        assert "totalPages" in pagination
        assert "hasNextPage" in pagination
        assert "hasPreviousPage" in pagination

    async def test_nested_keys_are_converted(self, client, tenant):
        body = (await client.get(f"{API}/users/me", headers=headers_from_tokens(tenant["token"]))).json()
        assert isinstance(body, dict)


class TestErrorFormats:
    async def test_validation_error_format(self, client):
        response = await client.post(f"{API}/auth/register", json={})

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "Validation Error"
        assert body["message"] == "Invalid request data"
        assert isinstance(body["details"], list)
        assert {"path", "message"} <= set(body["details"][0].keys())

    async def test_app_error_format(self, client):
        response = await client.post(
            f"{API}/auth/login", json={"email": "nobody@example.com", "password": "Password123"}
        )

        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "UnauthorizedError"
        assert "message" in body

    async def test_not_found_error_format(self, client, tenant_headers):
        response = await client.get(f"{API}/users/999999", headers=tenant_headers)

        assert response.status_code == 404
        assert response.json() == {"error": "NotFoundError", "message": "User not found"}

    async def test_unhandled_error_is_masked(self, client, landlord_headers):
        from app.tests.conftest import listing_payload

        response = await client.post(
            f"{API}/listings/", json=listing_payload(price=-5), headers=landlord_headers
        )

        assert response.status_code == 500
        body = response.json()
        assert body["error"] == "Internal Server Error"
        assert body["message"] == "An unexpected error occurred"


class TestHttpMethodNotFound:
    async def test_unknown_route_returns_404(self, client):
        response = await client.get(f"{API}/does-not-exist")

        assert response.status_code == 404
        assert response.json() == {"error": "NotFoundError", "message": "Not Found"}
