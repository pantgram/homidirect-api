from datetime import datetime

from app.config.database import Base
from app.tests.conftest import API, create_listing, headers_from_tokens, slot_payload, sync_user


async def create_slot(client, headers, listing_id):
    response = await client.post(f"{API}/availability-slots/", json=slot_payload(listing_id), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["slot"]


async def create_booking(client, headers, listing_id, landlord_headers):
    """Create a fresh slot (only landlords can) and book it. The returned booking dict carries
    the created slot under the extra "slot" key for assertions."""
    slot = await create_slot(client, landlord_headers, listing_id)
    response = await client.post(
        f"{API}/bookings/",
        json={"listingId": listing_id, "availabilitySlotId": slot["id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    booking = response.json()["booking"]
    booking["slot"] = slot
    return booking


def _as_naive_utc(dt: datetime) -> datetime:
    """Drop tzinfo for comparisons: SQLite (test DB) returns naive datetimes and test slots are UTC."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class TestCreateBooking:
    async def test_create_booking(
        self, client, listing, tenant, tenant_headers, landlord_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        assert booking["status"] == "PENDING"
        assert booking["candidateId"] == tenant["user"]["id"]
        assert booking["landlordId"] == listing["landlordId"]
        assert booking["listingId"] == listing["id"]
        assert booking["availabilitySlotId"] == slot["id"]
        assert _as_naive_utc(datetime.fromisoformat(booking["scheduledAt"])) == _as_naive_utc(
            datetime.fromisoformat(slot["startTime"])
        )
        mock_external_services["booking_created"].assert_awaited_once()

    async def test_availability_slot_id_required(self, client, listing, tenant_headers):
        response = await client.post(f"{API}/bookings/", json={"listingId": listing["id"]}, headers=tenant_headers)

        assert response.status_code == 422

    async def test_past_dated_slot_rejected(self, client, listing, landlord_headers, tenant_headers):
        response = await client.post(
            f"{API}/availability-slots/",
            json=slot_payload(listing["id"], hours_from_now=-1),
            headers=landlord_headers,
        )
        assert response.status_code == 201, response.text
        slot = response.json()["slot"]

        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": listing["id"], "availabilitySlotId": slot["id"]},
            headers=tenant_headers,
        )

        assert response.status_code == 400

    async def test_cannot_book_own_listing(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": listing["id"], "availabilitySlotId": slot["id"]},
            headers=landlord_headers,
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot book your own listing"

    async def test_unknown_listing(self, client, tenant_headers):
        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": 999999, "availabilitySlotId": 999999},
            headers=tenant_headers,
        )

        assert response.status_code == 404

    async def test_booking_with_slot_marks_it_booked(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert available.json()["slots"] == []

    async def test_cannot_double_book_slot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": listing["id"], "availabilitySlotId": slot["id"]},
            headers=tenant_headers,
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Availability slot is already booked"

    async def test_unique_index_backstop_maps_to_conflict(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        # Simulate the losing side of a concurrent race: the is_booked flag says free, but a
        # booking row already exists. The unique index, not the flag check, must produce the 409.
        unflag = await client.patch(
            f"{API}/availability-slots/{slot['id']}", json={"isBooked": False}, headers=landlord_headers
        )
        assert unflag.status_code == 200, unflag.text

        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": listing["id"], "availabilitySlotId": slot["id"]},
            headers=tenant_headers,
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Availability slot is already booked"

    async def test_slot_from_other_listing_rejected(self, client, landlord_headers, tenant_headers):
        first = await create_listing(client, landlord_headers, titleEl="First")
        second = await create_listing(client, landlord_headers, titleEl="Second")
        slot = await create_slot(client, landlord_headers, first["id"])

        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": second["id"], "availabilitySlotId": slot["id"]},
            headers=tenant_headers,
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Availability slot not found"

    async def test_requires_authentication(self, client, listing):
        response = await client.post(f"{API}/bookings/", json={"listingId": listing["id"], "availabilitySlotId": 1})

        assert response.status_code == 401

    def test_unique_index_exists_in_metadata(self):
        indexes = Base.metadata.tables["bookings"].indexes
        assert any(ix.name == "uq_bookings_availability_slot_id" and ix.unique for ix in indexes)


class TestGetBookings:
    async def test_parties_see_booking_others_cannot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        as_tenant = await client.get(f"{API}/bookings/{booking['id']}", headers=tenant_headers)
        assert as_tenant.status_code == 200
        assert as_tenant.json()["booking"]["id"] == booking["id"]

        as_landlord = await client.get(f"{API}/bookings/{booking['id']}", headers=landlord_headers)
        assert as_landlord.status_code == 200

        outsider = await sync_user(client, email="outsider@example.com")
        outsider_headers = headers_from_tokens(outsider)
        as_outsider = await client.get(f"{API}/bookings/{booking['id']}", headers=outsider_headers)
        assert as_outsider.status_code == 404
        assert as_outsider.json()["message"] == "Booking not found"

    async def test_bookings_by_user(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        mine = await client.get(f"{API}/bookings/", headers=tenant_headers)
        assert mine.status_code == 200
        assert len(mine.json()["bookings"]) == 1

        theirs = await client.get(f"{API}/bookings/", headers=landlord_headers)
        assert len(theirs.json()["bookings"]) == 1

    async def test_bookings_by_listing(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.get(f"{API}/bookings/listing/{listing['id']}", headers=tenant_headers)

        assert response.status_code == 403

    async def test_unknown_booking(self, client, tenant_headers):
        response = await client.get(f"{API}/bookings/999999", headers=tenant_headers)

        assert response.status_code == 404


class TestUpdateBooking:
    async def test_landlord_confirms_booking(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["booking"]["status"] == "CONFIRMED"
        mock_external_services["booking_confirmed"].assert_awaited_once()

    async def test_tenant_cannot_confirm(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=tenant_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Only landlord can confirm or decline bookings"

    async def test_invalid_transition(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        await client.patch(f"{API}/bookings/{booking['id']}", json={"status": "DECLINED"}, headers=landlord_headers)

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 409
        assert "Cannot transition booking from DECLINED to CONFIRMED" in response.json()["message"]

    async def test_candidate_can_cancel(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CANCELLED"}, headers=tenant_headers
        )

        assert response.status_code == 200
        assert response.json()["booking"]["status"] == "CANCELLED"

    async def test_cancel_frees_slot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CANCELLED"}, headers=tenant_headers
        )
        assert response.status_code == 200

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["slots"]] == [slot["id"]]

    async def test_decline_frees_slot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "DECLINED"}, headers=landlord_headers
        )
        assert response.status_code == 200

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["slots"]] == [slot["id"]]


class TestSlotGuards:
    async def test_delete_booked_slot_conflict(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.delete(
            f"{API}/availability-slots/{booking['slot']['id']}", headers=landlord_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot delete a booked slot"

    async def test_cannot_reschedule_booked_slot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]
        new_start = slot_payload(listing["id"], hours_from_now=72)["startTime"]

        response = await client.patch(
            f"{API}/availability-slots/{slot['id']}", json={"startTime": new_start}, headers=landlord_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot change the time of a booked slot"


class TestDeleteBooking:
    async def test_delete_booking_frees_slot(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        slot = booking["slot"]

        response = await client.delete(f"{API}/bookings/{booking['id']}", headers=tenant_headers)

        assert response.status_code == 204
        mock_external_services["booking_cancelled"].assert_awaited_once()

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["slots"]] == [slot["id"]]

    async def test_outsider_cannot_delete(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        outsider = await sync_user(client, email="delete-outsider@example.com")
        outsider_headers = headers_from_tokens(outsider)

        response = await client.delete(f"{API}/bookings/{booking['id']}", headers=outsider_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Booking not found"
