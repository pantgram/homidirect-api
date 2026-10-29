from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.listing import Listing
from app.tests.conftest import API, create_listing, headers_from_tokens, listing_payload, sync_user


async def set_featured_until(session, listing_id: int, featured_until: datetime | None):
    """Write featured_until directly: the admin endpoint only accepts future dates,
    so expired windows (the interesting filter case) can't be created through the API.
    The naive UTC wall clock matches SQLite's CURRENT_TIMESTAMP for string comparison."""
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one()
    listing.featured_until = featured_until
    await session.commit()


def featured_until_payload(days: float = 7) -> dict:
    return {"featuredUntil": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}


class TestCreateListing:
    async def test_create_listing(self, client, landlord_headers):
        body = await create_listing(client, landlord_headers, titleEl="Προς νομή")

        assert body["price"] == 850.0
        assert body["city"] == "Athens"
        assert body["titleEl"] == "Προς νομή"
        assert body["verificationStatus"] == "PENDING"
        assert body["featuredUntil"] is None
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


class TestDateBuiltValidation:
    async def test_create_rejects_year_below_minimum(self, client, landlord_headers):
        response = await client.post(f"{API}/listings/", json=listing_payload(dateBuilt=1700), headers=landlord_headers)

        assert response.status_code == 422

    async def test_create_rejects_future_year(self, client, landlord_headers):
        response = await client.post(f"{API}/listings/", json=listing_payload(dateBuilt=3000), headers=landlord_headers)

        assert response.status_code == 422

    async def test_create_accepts_current_year(self, client, landlord_headers):
        body = await create_listing(client, landlord_headers, dateBuilt=date.today().year)

        assert body["dateBuilt"] == date.today().year

    async def test_update_rejects_invalid_year(self, client, listing, landlord_headers):
        response = await client.patch(
            f"{API}/listings/{listing['id']}", json={"dateBuilt": 1700}, headers=landlord_headers
        )

        assert response.status_code == 422

    async def test_search_rejects_invalid_min_date_built(self, client):
        response = await client.get(f"{API}/listings/search", params={"minDateBuilt": 1700})

        assert response.status_code == 422

    async def test_search_filters_by_date_built_range(self, client, landlord_headers):
        old = await create_listing(client, landlord_headers, dateBuilt=1980)
        new = await create_listing(client, landlord_headers, dateBuilt=2020)

        recent = await client.get(f"{API}/listings/search", params={"minDateBuilt": 2000})

        assert [item["id"] for item in recent.json()["data"]] == [new["id"]]

        old_range = await client.get(f"{API}/listings/search", params={"minDateBuilt": 1900, "maxDateBuilt": 1990})

        assert [item["id"] for item in old_range.json()["data"]] == [old["id"]]


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
        other = await sync_user(client, email="other-landlord@example.com", role="LANDLORD")
        headers = headers_from_tokens(other)

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
        other = await sync_user(client, email="second-landlord@example.com", role="LANDLORD")
        other_headers = headers_from_tokens(other)
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

    async def test_search_default_featured_sort(self, client, landlord_headers, admin_headers):
        plain = await create_listing(client, landlord_headers, price=100.0)
        featured = await create_listing(client, landlord_headers, price=200.0)

        response = await client.post(
            f"{API}/listings/{featured['id']}/feature", json=featured_until_payload(), headers=admin_headers
        )
        assert response.status_code == 200

        response = await client.get(f"{API}/listings/search")

        assert response.status_code == 200
        assert response.json()["pagination"]["total"] == 2
        assert [item["id"] for item in response.json()["data"]] == [featured["id"], plain["id"]]

    async def test_search_requires_no_authentication(self, client, listing):
        response = await client.get(f"{API}/listings/search")

        assert response.status_code == 200
        assert response.json()["pagination"]["total"] == 1


class TestFeaturedFilter:
    async def test_is_featured_true_returns_only_active_window(self, client, session, landlord_headers):
        featured = await create_listing(client, landlord_headers)
        expired = await create_listing(client, landlord_headers)
        await create_listing(client, landlord_headers)  # never featured

        await set_featured_until(session, featured["id"], datetime.now(timezone.utc) + timedelta(days=7))
        await set_featured_until(session, expired["id"], datetime.now(timezone.utc) - timedelta(days=1))

        response = await client.get(f"{API}/listings/search", params={"isFeatured": "true"})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]] == [featured["id"]]

    async def test_is_featured_false_excludes_active_window(self, client, session, landlord_headers):
        featured = await create_listing(client, landlord_headers)
        never = await create_listing(client, landlord_headers)
        expired = await create_listing(client, landlord_headers)

        await set_featured_until(session, featured["id"], datetime.now(timezone.utc) + timedelta(days=7))
        await set_featured_until(session, expired["id"], datetime.now(timezone.utc) - timedelta(days=1))

        response = await client.get(f"{API}/listings/search", params={"isFeatured": "false"})

        assert response.status_code == 200
        assert {item["id"] for item in response.json()["data"]} == {never["id"], expired["id"]}


class TestFeatureAdmin:
    async def test_feature_sets_featured_until(self, client, listing, admin_headers):
        response = await client.post(
            f"{API}/listings/{listing['id']}/feature", json=featured_until_payload(), headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["listing"]["featuredUntil"] is not None

        search = await client.get(f"{API}/listings/search", params={"isFeatured": "true"})
        assert [item["id"] for item in search.json()["data"]] == [listing["id"]]

    async def test_feature_rejects_past_date(self, client, listing, admin_headers):
        payload = {"featuredUntil": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}

        response = await client.post(f"{API}/listings/{listing['id']}/feature", json=payload, headers=admin_headers)

        assert response.status_code == 422

    async def test_feature_forbidden_for_landlord(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/listings/{listing['id']}/feature", json=featured_until_payload(), headers=landlord_headers
        )

        assert response.status_code == 403
        assert response.json()["message"] == "Admin access required"

    async def test_feature_forbidden_for_tenant(self, client, listing, tenant_headers):
        response = await client.post(
            f"{API}/listings/{listing['id']}/feature", json=featured_until_payload(), headers=tenant_headers
        )

        assert response.status_code == 403

    async def test_feature_requires_authentication(self, client, listing):
        response = await client.post(f"{API}/listings/{listing['id']}/feature", json=featured_until_payload())

        assert response.status_code == 401

    async def test_feature_unknown_listing(self, client, admin_headers):
        response = await client.post(
            f"{API}/listings/999999/feature", json=featured_until_payload(), headers=admin_headers
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Listing not found"

    async def test_unfeature_clears_featured_until(self, client, listing, admin_headers):
        feature = await client.post(
            f"{API}/listings/{listing['id']}/feature", json=featured_until_payload(), headers=admin_headers
        )
        assert feature.status_code == 200

        response = await client.delete(f"{API}/listings/{listing['id']}/feature", headers=admin_headers)

        assert response.status_code == 204

        follow_up = await client.get(f"{API}/listings/{listing['id']}")
        assert follow_up.json()["listing"]["featuredUntil"] is None

        search = await client.get(f"{API}/listings/search", params={"isFeatured": "true"})
        assert search.json()["data"] == []

    async def test_unfeature_unknown_listing(self, client, admin_headers):
        response = await client.delete(f"{API}/listings/999999/feature", headers=admin_headers)

        assert response.status_code == 404


class TestStatsAndCities:
    async def test_stats(self, client, landlord_headers):
        await create_listing(client, landlord_headers)
        await create_listing(client, landlord_headers)

        response = await client.get(f"{API}/listings/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["activeListingsCount"] == 2
        assert body["propertyOwnersCount"] == 1

    async def test_cities_distinct_and_sorted(self, client, landlord_headers):
        await create_listing(client, landlord_headers, city="Thessaloniki")
        await create_listing(client, landlord_headers, city="Athens")
        await create_listing(client, landlord_headers, city="Athens")

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
