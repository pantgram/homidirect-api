from app.tests.conftest import API, create_listing, listing_payload


class TestCreateListing:
    async def test_create_listing(self, client, landlord_headers):
        body = await create_listing(client, landlord_headers, titleEl="Προς νομή")

        assert body["price"] == 850.0
        assert body["city"] == "Athens"
        assert body["titleEl"] == "Προς νομή"
        assert body["verificationStatus"] == "PENDING"
        assert body["isFeatured"] is False
        assert body["id"] > 0
        assert body["createdAt"]
        assert body["dateAvailable"] == "2026-10-01"

    async def test_landlord_id_is_forced_to_current_user(self, client, landlord, landlord_headers):
        body = await create_listing(client, landlord_headers, landlordId=999999)

        assert body["landlordId"] == landlord["user"]["id"]

    async def test_tenant_cannot_create_listing(self, client, tenant_headers):
        response = await client.post(
            f"{API}/listings/", json=listing_payload(), headers=tenant_headers
        )

        assert response.status_code == 403
        assert response.json()["message"] == "Insufficient permissions"

    async def test_requires_authentication(self, client):
        response = await client.post(f"{API}/listings/", json=listing_payload())

        assert response.status_code == 401

    async def test_missing_required_fields(self, client, landlord_headers):
        response = await client.post(f"{API}/listings/", json={"city": "Athens"}, headers=landlord_headers)

        assert response.status_code == 422
        paths = {d["path"] for d in response.json()["details"]}
        assert "price" in paths
        assert "propertyType" in paths

    async def test_negative_price_rejected_by_db_constraint(self, client, landlord_headers):
        response = await client.post(
            f"{API}/listings/", json=listing_payload(price=-100), headers=landlord_headers
        )

        assert response.status_code == 500
        assert response.json()["error"] == "Internal Server Error"


class TestGetListing:
    async def test_get_listing_by_id(self, client, listing):
        response = await client.get(f"{API}/listings/{listing['id']}")

        assert response.status_code == 200
        body = response.json()["listing"]
        assert body["id"] == listing["id"]
        assert body["city"] == "Athens"
        assert body["bedrooms"] == 2

    async def test_get_unknown_listing(self, client):
        response = await client.get(f"{API}/listings/999999")

        assert response.status_code == 404
        assert response.json() == {"error": "NotFoundError", "message": "Listing not found"}

    async def test_get_all_listings(self, client, landlord_headers):
        await create_listing(client, landlord_headers, titleEl="One")
        await create_listing(client, landlord_headers, titleEl="Two")

        response = await client.get(f"{API}/listings/")

        assert response.status_code == 200
        assert len(response.json()["listings"]) == 2


class TestUpdateListing:
    async def test_update_price(self, client, listing, landlord_headers):
        response = await client.patch(
            f"{API}/listings/{listing['id']}", json={"price": 950.0, "bedrooms": 3}, headers=landlord_headers
        )

        assert response.status_code == 200
        body = response.json()["listing"]
        assert body["price"] == 950.0
        assert body["bedrooms"] == 3

    async def test_non_owner_cannot_update(self, client, listing):
        other = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Other",
                "lastName": "Landlord",
                "email": "other-landlord@example.com",
                "password": "Password123",
                "role": "LANDLORD",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['token']['accessToken']}"}

        response = await client.patch(f"{API}/listings/{listing['id']}", json={"price": 1.0}, headers=headers)

        assert response.status_code == 403
        assert response.json()["message"] == "You do not own this listing"

    async def test_admin_can_update_any_listing(self, client, listing, admin_headers):
        response = await client.patch(
            f"{API}/listings/{listing['id']}", json={"price": 777.0}, headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["listing"]["price"] == 777.0

    async def test_update_unknown_listing(self, client, landlord_headers):
        response = await client.patch(f"{API}/listings/999999", json={"price": 1.0}, headers=landlord_headers)

        assert response.status_code == 404


class TestDeleteListing:
    async def test_delete_listing(self, client, listing, landlord_headers):
        response = await client.delete(f"{API}/listings/{listing['id']}", headers=landlord_headers)

        assert response.status_code == 204

        follow_up = await client.get(f"{API}/listings/{listing['id']}")
        assert follow_up.status_code == 404

    async def test_non_owner_cannot_delete(self, client, listing, tenant_headers):
        response = await client.delete(f"{API}/listings/{listing['id']}", headers=tenant_headers)

        assert response.status_code == 403

    async def test_delete_unknown_listing(self, client, landlord_headers):
        response = await client.delete(f"{API}/listings/999999", headers=landlord_headers)

        assert response.status_code == 404


class TestMyListings:
    async def test_returns_only_own_listings(self, client, landlord_headers):
        first = await create_listing(client, landlord_headers, titleEl="Mine")
        other = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Second",
                "lastName": "Landlord",
                "email": "second-landlord@example.com",
                "password": "Password123",
                "role": "LANDLORD",
            },
        )
        other_headers = {"Authorization": f"Bearer {other.json()['token']['accessToken']}"}
        await create_listing(client, other_headers, titleEl="Theirs")

        response = await client.get(f"{API}/listings/my-listings", headers=landlord_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["total"] == 1
        assert body["data"][0]["id"] == first["id"]

    async def test_tenant_forbidden(self, client, tenant_headers):
        response = await client.get(f"{API}/listings/my-listings", headers=tenant_headers)

        assert response.status_code == 403


class TestSearch:
    async def test_search_by_text(self, client, landlord_headers):
        await create_listing(client, landlord_headers, titleEl="Παλιό σπίτι", city="Patras")
        match = await create_listing(client, landlord_headers, titleEn="Sunny apartment")

        response = await client.get(f"{API}/listings/search", params={"q": "Sunny"})

        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["total"] == 1
        assert body["data"][0]["id"] == match["id"]

    async def test_search_filters(self, client, landlord_headers):
        cheap = await create_listing(client, landlord_headers, price=300.0, city="Athens", bedrooms=1)
        await create_listing(client, landlord_headers, price=1500.0, city="Thessaloniki", bedrooms=3)

        response = await client.get(
            f"{API}/listings/search",
            params={"city": "Athens", "minPrice": 200, "maxPrice": 500, "bedrooms": 1},
        )

        body = response.json()
        assert [item["id"] for item in body["data"]] == [cheap["id"]]

    async def test_search_boolean_filters(self, client, landlord_headers):
        await create_listing(client, landlord_headers, elevator=True, parkingSpace=True)
        no_elevator = await create_listing(client, landlord_headers, elevator=False)

        response = await client.get(f"{API}/listings/search", params={"elevator": "false"})

        assert [item["id"] for item in response.json()["data"]] == [no_elevator["id"]]

    async def test_search_pagination(self, client, landlord_headers):
        for i in range(3):
            await create_listing(client, landlord_headers, price=float(100 + i))

        response = await client.get(f"{API}/listings/search", params={"limit": 2, "page": 1, "sortBy": "price_asc"})

        body = response.json()
        assert body["pagination"]["total"] == 3
        assert body["pagination"]["totalPages"] == 2
        assert body["pagination"]["hasNextPage"] is True
        assert body["pagination"]["hasPreviousPage"] is False
        assert len(body["data"]) == 2

        page2 = await client.get(f"{API}/listings/search", params={"limit": 2, "page": 2, "sortBy": "price_asc"})
        assert page2.json()["pagination"]["hasNextPage"] is False
        assert page2.json()["pagination"]["hasPreviousPage"] is True
        assert len(page2.json()["data"]) == 1

    async def test_search_sort_price_ascending(self, client, landlord_headers):
        await create_listing(client, landlord_headers, price=900.0)
        await create_listing(client, landlord_headers, price=100.0)
        await create_listing(client, landlord_headers, price=500.0)

        response = await client.get(f"{API}/listings/search", params={"sortBy": "price_asc"})

        prices = [item["price"] for item in response.json()["data"]]
        assert prices == sorted(prices)

    async def test_search_default_featured_sort(self, client, landlord_headers):
        await create_listing(client, landlord_headers, price=100.0)

        response = await client.get(f"{API}/listings/search")

        assert response.status_code == 200
        assert response.json()["pagination"]["total"] == 1

    async def test_search_available_filter(self, client, landlord_headers):
        available = await create_listing(client, landlord_headers)
        await create_listing(client, landlord_headers, available=False)

        response = await client.get(f"{API}/listings/search", params={"available": "true"})

        assert [item["id"] for item in response.json()["data"]] == [available["id"]]

    async def test_search_requires_no_authentication(self, client, listing):
        response = await client.get(f"{API}/listings/search")

        assert response.status_code == 200
        assert response.json()["pagination"]["total"] == 1


class TestStatsAndCities:
    async def test_stats(self, client, landlord_headers):
        await create_listing(client, landlord_headers)
        await create_listing(client, landlord_headers, available=False)

        response = await client.get(f"{API}/listings/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["activeListingsCount"] == 1
        assert body["propertyOwnersCount"] == 1

    async def test_cities_distinct_and_sorted(self, client, landlord_headers):
        await create_listing(client, landlord_headers, city="Thessaloniki")
        await create_listing(client, landlord_headers, city="Athens")
        await create_listing(client, landlord_headers, city="Athens")
        await create_listing(client, landlord_headers, city="Patras", available=False)

        response = await client.get(f"{API}/listings/cities")

        assert response.status_code == 200
        assert response.json() == ["Athens", "Thessaloniki"]


class TestContactOwner:
    async def test_contact_owner_queues_email(self, client, listing, tenant_headers, mock_external_services):
        response = await client.post(
            f"{API}/listings/{listing['id']}/contact",
            json={"name": "Interested Person", "email": "interested@example.com", "message": "Is this available?"},
            headers=tenant_headers,
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Contact email sent"
        mock_external_services["contact_owner"].assert_awaited_once()
        args = mock_external_services["contact_owner"].await_args.args
        assert args[0] == "landlord@example.com"
        assert args[1] == "Interested Person"

    async def test_contact_requires_authentication(self, client, listing):
        response = await client.post(
            f"{API}/listings/{listing['id']}/contact",
            json={"name": "X", "email": "x@example.com", "message": "hi"},
        )

        assert response.status_code == 401

    async def test_contact_unknown_listing(self, client, tenant_headers):
        response = await client.post(
            f"{API}/listings/999999/contact",
            json={"name": "X", "email": "x@example.com", "message": "hi"},
            headers=tenant_headers,
        )

        assert response.status_code == 404
