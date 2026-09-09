from app.tests.conftest import API, create_listing, slot_payload


async def create_slot(client, headers, listing_id):
    response = await client.post(f"{API}/availability-slots/", json=slot_payload(listing_id), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["slot"]


async def create_booking(client, headers, listing_id, scheduled_at="2026-12-01T15:00:00", slot_id=None):
    payload = {"listingId": listing_id, "scheduledAt": scheduled_at}
    if slot_id is not None:
        payload["availabilitySlotId"] = slot_id
    response = await client.post(f"{API}/bookings/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["booking"]


class TestCreateBooking:
    async def test_create_booking(self, client, listing, tenant, tenant_headers, mock_external_services):
        booking = await create_booking(client, tenant_headers, listing["id"])

        assert booking["status"] == "PENDING"
        assert booking["candidateId"] == tenant["user"]["id"]
        assert booking["landlordId"] == listing["landlordId"]
        assert booking["listingId"] == listing["id"]
        assert booking["availabilitySlotId"] is None
        mock_external_services["booking_created"].assert_awaited_once()

    async def test_cannot_book_own_listing(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": listing["id"], "scheduledAt": "2026-12-01T15:00:00"},
            headers=landlord_headers,
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot book your own listing"

    async def test_unknown_listing(self, client, tenant_headers):
        response = await client.post(
            f"{API}/bookings/",
            json={"listingId": 999999, "scheduledAt": "2026-12-01T15:00:00"},
            headers=tenant_headers,
        )

        assert response.status_code == 404

    async def test_booking_with_slot_marks_it_booked(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        await create_booking(client, tenant_headers, listing["id"], slot_id=slot["id"])

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert available.json()["slots"] == []

    async def test_cannot_double_book_slot(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])
        await create_booking(client, tenant_headers, listing["id"], slot_id=slot["id"])

        response = await client.post(
            f"{API}/bookings/",
            json={
                "listingId": listing["id"],
                "scheduledAt": "2026-12-02T15:00:00",
                "availabilitySlotId": slot["id"],
            },
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
            json={
                "listingId": second["id"],
                "scheduledAt": "2026-12-01T15:00:00",
                "availabilitySlotId": slot["id"],
            },
            headers=tenant_headers,
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Availability slot not found"

    async def test_requires_authentication(self, client, listing):
        response = await client.post(
            f"{API}/bookings/", json={"listingId": listing["id"], "scheduledAt": "2026-12-01T15:00:00"}
        )

        assert response.status_code == 401


class TestGetBookings:
    async def test_parties_see_booking_others_cannot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])

        as_tenant = await client.get(f"{API}/bookings/{booking['id']}", headers=tenant_headers)
        assert as_tenant.status_code == 200
        assert as_tenant.json()["booking"]["id"] == booking["id"]

        as_landlord = await client.get(f"{API}/bookings/{booking['id']}", headers=landlord_headers)
        assert as_landlord.status_code == 200

        outsider = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Out",
                "lastName": "Sider",
                "email": "outsider@example.com",
                "password": "Password123",
                "role": "TENANT",
            },
        )
        outsider_headers = {"Authorization": f"Bearer {outsider.json()['token']['accessToken']}"}
        as_outsider = await client.get(f"{API}/bookings/{booking['id']}", headers=outsider_headers)
        assert as_outsider.status_code == 404
        assert as_outsider.json()["message"] == "Booking not found"

    async def test_bookings_by_user(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"])

        mine = await client.get(f"{API}/bookings/", headers=tenant_headers)
        assert mine.status_code == 200
        assert len(mine.json()["bookings"]) == 1

        theirs = await client.get(f"{API}/bookings/", headers=landlord_headers)
        assert len(theirs.json()["bookings"]) == 1

    async def test_bookings_by_listing(self, client, listing, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"])

        response = await client.get(f"{API}/bookings/listing/{listing['id']}", headers=tenant_headers)

        assert response.status_code == 403

    async def test_unknown_booking(self, client, tenant_headers):
        response = await client.get(f"{API}/bookings/999999", headers=tenant_headers)

        assert response.status_code == 404


class TestUpdateBooking:
    async def test_landlord_confirms_booking(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"])

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["booking"]["status"] == "CONFIRMED"
        mock_external_services["booking_confirmed"].assert_awaited_once()

    async def test_tenant_cannot_confirm(self, client, listing, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=tenant_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Only landlord can confirm or decline bookings"

    async def test_invalid_transition(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])
        await client.patch(f"{API}/bookings/{booking['id']}", json={"status": "DECLINED"}, headers=landlord_headers)

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 409
        assert "Cannot transition booking from DECLINED to CONFIRMED" in response.json()["message"]

    async def test_candidate_can_cancel(self, client, listing, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])

        response = await client.patch(
            f"{API}/bookings/{booking['id']}", json={"status": "CANCELLED"}, headers=tenant_headers
        )

        assert response.status_code == 200
        assert response.json()["booking"]["status"] == "CANCELLED"

    async def test_reschedule_scheduled_at(self, client, listing, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])

        response = await client.patch(
            f"{API}/bookings/{booking['id']}",
            json={"scheduledAt": "2027-01-15T10:00:00"},
            headers=tenant_headers,
        )

        assert response.status_code == 200
        assert response.json()["booking"]["scheduledAt"].startswith("2027-01-15T10:00:00")


class TestDeleteBooking:
    async def test_delete_booking_frees_slot(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        slot = await create_slot(client, landlord_headers, listing["id"])
        booking = await create_booking(client, tenant_headers, listing["id"], slot_id=slot["id"])

        response = await client.delete(f"{API}/bookings/{booking['id']}", headers=tenant_headers)

        assert response.status_code == 204
        mock_external_services["booking_cancelled"].assert_awaited_once()

        available = await client.get(f"{API}/availability-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["slots"]] == [slot["id"]]

    async def test_outsider_cannot_delete(self, client, listing, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"])
        outsider = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Out",
                "lastName": "Sider",
                "email": "delete-outsider@example.com",
                "password": "Password123",
                "role": "TENANT",
            },
        )
        outsider_headers = {"Authorization": f"Bearer {outsider.json()['token']['accessToken']}"}

        response = await client.delete(f"{API}/bookings/{booking['id']}", headers=outsider_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Booking not found"
