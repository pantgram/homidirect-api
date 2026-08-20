from datetime import datetime, timedelta, timezone

from app.tests.conftest import API, slot_payload


def iso(dt: datetime) -> str:
    return dt.isoformat()


class TestCreateSlot:
    async def test_create_slot(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )

        assert response.status_code == 201
        body = response.json()["slot"]
        assert body["listingId"] == listing["id"]
        assert body["landlordId"] == listing["landlordId"]
        assert body["isBooked"] is False

    async def test_end_time_must_be_after_start_time(self, client, listing, landlord_headers):
        start = datetime.now(timezone.utc) + timedelta(days=1)
        payload = {"listingId": listing["id"], "startTime": iso(start), "endTime": iso(start - timedelta(hours=1))}

        response = await client.post(f"{API}/availability-slots/", json=payload, headers=landlord_headers)

        assert response.status_code == 422

    async def test_unknown_listing(self, client, landlord_headers):
        response = await client.post(
            f"{API}/availability-slots/", json=slot_payload(999999), headers=landlord_headers
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Listing not found"

    async def test_non_owner_cannot_create_slot(self, client, listing):
        other = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Other",
                "lastName": "Landlord",
                "email": "slot-landlord@example.com",
                "password": "Password123",
                "role": "LANDLORD",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['token']['accessToken']}"}

        response = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=headers
        )

        assert response.status_code == 403
        assert response.json()["message"] == "You do not own this listing"

    async def test_tenant_cannot_create_slot(self, client, listing, tenant_headers):
        response = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=tenant_headers
        )

        assert response.status_code == 403


class TestGetSlots:
    async def test_available_slots_exclude_past_and_booked(self, client, listing, landlord_headers, session):
        from app.models.availability_slot import AvailabilitySlot

        future = slot_payload(listing["id"], hours_from_now=48)
        past_payload = slot_payload(listing["id"], hours_from_now=-48)
        booked_payload = slot_payload(listing["id"], hours_from_now=72)

        await client.post(f"{API}/availability-slots/", json=future, headers=landlord_headers)
        await client.post(f"{API}/availability-slots/", json=past_payload, headers=landlord_headers)
        booked = await client.post(f"{API}/availability-slots/", json=booked_payload, headers=landlord_headers)
        booked_id = booked.json()["slot"]["id"]

        slot = await session.get(AvailabilitySlot, booked_id)
        slot.is_booked = True
        await session.commit()

        response = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")

        assert response.status_code == 200
        slots = response.json()["slots"]
        assert len(slots) == 1
        assert slots[0]["startTime"].startswith(future["startTime"][:19])

    async def test_all_slots_by_listing(self, client, listing, landlord_headers):
        await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"], hours_from_now=24), headers=landlord_headers
        )
        await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"], hours_from_now=48), headers=landlord_headers
        )

        response = await client.get(f"{API}/availability-slots/listing/{listing['id']}")

        assert response.status_code == 200
        assert len(response.json()["slots"]) == 2

    async def test_get_slot_by_id(self, client, listing, landlord_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]

        response = await client.get(f"{API}/availability-slots/{slot_id}")

        assert response.status_code == 200
        assert response.json()["slot"]["id"] == slot_id

    async def test_get_unknown_slot(self, client):
        response = await client.get(f"{API}/availability-slots/999999")

        assert response.status_code == 404
        assert response.json()["message"] == "Availability slot not found"


class TestUpdateSlot:
    async def test_update_start_time(self, client, listing, landlord_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]
        new_start = datetime.now(timezone.utc) + timedelta(days=7)

        response = await client.patch(
            f"{API}/availability-slots/{slot_id}", json={"startTime": iso(new_start)}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["slot"]["startTime"].startswith(new_start.strftime("%Y-%m-%dT"))

    async def test_non_owner_cannot_update(self, client, listing, landlord_headers, tenant_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]

        response = await client.patch(
            f"{API}/availability-slots/{slot_id}", json={"isBooked": True}, headers=tenant_headers
        )

        assert response.status_code == 403
        assert response.json()["message"] == "You do not own this slot"

    async def test_admin_can_update_any_slot(self, client, listing, landlord_headers, admin_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]

        response = await client.patch(
            f"{API}/availability-slots/{slot_id}", json={"isBooked": True}, headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["slot"]["isBooked"] is True


class TestDeleteSlot:
    async def test_delete_slot(self, client, listing, landlord_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]

        response = await client.delete(f"{API}/availability-slots/{slot_id}", headers=landlord_headers)

        assert response.status_code == 204

        follow_up = await client.get(f"{API}/availability-slots/{slot_id}")
        assert follow_up.status_code == 404

    async def test_non_owner_cannot_delete(self, client, listing, landlord_headers, tenant_headers):
        created = await client.post(
            f"{API}/availability-slots/", json=slot_payload(listing["id"]), headers=landlord_headers
        )
        slot_id = created.json()["slot"]["id"]

        response = await client.delete(f"{API}/availability-slots/{slot_id}", headers=tenant_headers)

        assert response.status_code == 403
