from datetime import datetime, timedelta, timezone

from app.tests.conftest import API, headers_from_tokens, slot_payload, sync_user

# --- Helpers ---


def iso(dt: datetime) -> str:
    return dt.isoformat()


def _as_naive_utc(dt: datetime) -> datetime:
    """Drop tzinfo for comparisons: SQLite (test DB) returns naive datetimes and test slots are UTC."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def create_slot(client, headers, listing_id, **overrides):
    response = await client.post(f"{API}/time-slots", json=slot_payload(listing_id, **overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["timeSlot"]


async def claim_slot(client, headers, slot_id, **extra):
    return await client.post(f"{API}/time-slots/{slot_id}/claim", json=dict(extra), headers=headers)


async def create_booking(client, headers, listing_id, landlord_headers):
    """Create a fresh slot (only landlords can) and claim it. The returned dict is the
    claimed slot itself — a booking is just a claimed slot, so its id IS the slot id."""
    slot = await create_slot(client, landlord_headers, listing_id)
    response = await claim_slot(client, headers, slot["id"])
    assert response.status_code == 201, response.text
    return response.json()["timeSlot"]


async def propose_slot(client, headers, listing_id, hours_from_now=48, **overrides):
    payload = slot_payload(listing_id, hours_from_now=hours_from_now)
    payload.update(overrides)
    return await client.post(f"{API}/time-slots/propose", json=payload, headers=headers)


# --- Claim (formerly POST /bookings) ---


class TestClaim:
    async def test_claim_slot(self, client, listing, tenant, tenant_headers, landlord_headers, mock_external_services):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await claim_slot(client, tenant_headers, slot["id"])

        assert response.status_code == 201, response.text
        body = response.json()["timeSlot"]
        assert body["id"] == slot["id"]
        assert body["status"] == "PENDING"
        assert body["isBooked"] is True
        assert body["candidateId"] == tenant["user"]["id"]
        assert body["landlordId"] == listing["landlordId"]
        assert body["listingId"] == listing["id"]
        assert body["type"] == "REMOTE"
        assert body["landlordCreated"] is True
        assert _as_naive_utc(datetime.fromisoformat(body["startTime"])) == _as_naive_utc(
            datetime.fromisoformat(slot["startTime"])
        )
        mock_external_services["booking_created"].assert_awaited_once()

    async def test_claim_with_meet_link(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await claim_slot(client, tenant_headers, slot["id"], meet_link="https://meet.example.com/x")

        assert response.status_code == 201, response.text
        assert response.json()["timeSlot"]["meetLink"] == "https://meet.example.com/x"

    async def test_meet_link_on_on_site_slot_rejected(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"], type="ON_SITE")

        response = await claim_slot(client, tenant_headers, slot["id"], meet_link="https://meet.example.com/x")

        assert response.status_code == 400

    async def test_past_dated_slot_rejected(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"], hours_from_now=-1)

        response = await claim_slot(client, tenant_headers, slot["id"])

        assert response.status_code == 400

    async def test_cannot_claim_own_listing(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await claim_slot(client, landlord_headers, slot["id"])

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot book your own listing"

    async def test_unknown_slot(self, client, tenant_headers):
        response = await claim_slot(client, tenant_headers, 999999)

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"

    async def test_claimed_slot_disappears_from_availability(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert available.json()["timeSlots"] == []

    async def test_cannot_double_book_slot(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])
        await claim_slot(client, tenant_headers, slot["id"])

        response = await claim_slot(client, tenant_headers, slot["id"])

        assert response.status_code == 409
        assert response.json()["message"] == "Time slot is already booked"

    async def test_claim_is_atomic_on_status(self, client, listing, landlord_headers, tenant_headers, session):
        """Race safety: the claim is a conditional UPDATE on status. Simulate a concurrent
        claim that the API has not seen by flipping the status directly in the DB; the
        claim must still surface as 409."""
        slot = await create_slot(client, landlord_headers, listing["id"])

        from app.models.time_slot import TimeSlot

        row = await session.get(TimeSlot, slot["id"])
        row.status = "PENDING"
        await session.commit()

        response = await claim_slot(client, tenant_headers, slot["id"])

        assert response.status_code == 409
        assert response.json()["message"] == "Time slot is already booked"

    async def test_requires_authentication(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await claim_slot(client, None, slot["id"])

        assert response.status_code == 401


# --- Reads ---


class TestGetTimeSlots:
    async def test_parties_see_slot_others_cannot(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        as_tenant = await client.get(f"{API}/time-slots/{booking['id']}", headers=tenant_headers)
        assert as_tenant.status_code == 200
        assert as_tenant.json()["timeSlot"]["id"] == booking["id"]
        assert as_tenant.json()["timeSlot"]["candidateId"] == booking["candidateId"]

        as_landlord = await client.get(f"{API}/time-slots/{booking['id']}", headers=landlord_headers)
        assert as_landlord.status_code == 200

        outsider = await sync_user(client, email="outsider@example.com")
        outsider_headers = headers_from_tokens(outsider)
        as_outsider = await client.get(f"{API}/time-slots/{booking['id']}", headers=outsider_headers)
        assert as_outsider.status_code == 404
        assert as_outsider.json()["message"] == "Time slot not found"

    async def test_open_slot_is_public(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.get(f"{API}/time-slots/{slot['id']}")

        assert response.status_code == 200
        body = response.json()["timeSlot"]
        assert body["id"] == slot["id"]
        assert body["status"] == "OPEN"
        assert body["isBooked"] is False
        # Public shape: participant fields never leak.
        assert body["candidateId"] is None
        assert body["meetLink"] is None
        assert body["landlordCreated"] is None

    async def test_claimed_slot_hidden_from_anonymous(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.get(f"{API}/time-slots/{booking['id']}")

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"

    async def test_bookings_by_user(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        mine = await client.get(f"{API}/time-slots/me", headers=tenant_headers)
        assert mine.status_code == 200
        assert len(mine.json()["timeSlots"]) == 1

        theirs = await client.get(f"{API}/time-slots/me", headers=landlord_headers)
        assert len(theirs.json()["timeSlots"]) == 1

    async def test_open_slots_are_not_bookings(self, client, listing, landlord_headers, tenant_headers):
        """Unclaimed availability must not show up in either party's bookings list."""
        await create_slot(client, landlord_headers, listing["id"])

        as_landlord = await client.get(f"{API}/time-slots/me", headers=landlord_headers)
        assert as_landlord.json()["timeSlots"] == []

        as_tenant = await client.get(f"{API}/time-slots/me", headers=tenant_headers)
        assert as_tenant.json()["timeSlots"] == []

        by_listing = await client.get(f"{API}/time-slots/listing/{listing['id']}/bookings", headers=landlord_headers)
        assert by_listing.json()["timeSlots"] == []

    async def test_bookings_by_listing_requires_owner(self, client, listing, landlord_headers, tenant_headers):
        await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.get(f"{API}/time-slots/listing/{listing['id']}/bookings", headers=tenant_headers)

        assert response.status_code == 403

    async def test_unknown_slot(self, client, tenant_headers):
        response = await client.get(f"{API}/time-slots/999999", headers=tenant_headers)

        assert response.status_code == 404


# --- Status transitions ---


class TestTransitions:
    async def test_landlord_confirms_booking(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["timeSlot"]["status"] == "CONFIRMED"
        mock_external_services["booking_confirmed"].assert_awaited_once()

    async def test_tenant_cannot_confirm(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"status": "CONFIRMED"}, headers=tenant_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Only landlord can confirm or decline bookings"

    async def test_cannot_transition_out_of_confirmed(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        await client.patch(f"{API}/time-slots/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"status": "CONFIRMED"}, headers=landlord_headers
        )

        assert response.status_code == 409
        assert "Cannot transition booking from CONFIRMED to CONFIRMED" in response.json()["message"]

    async def test_cancel_releases_slot_with_same_id(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"status": "CANCELLED"}, headers=tenant_headers
        )

        assert response.status_code == 200
        # A landlord-created window returns to OPEN availability, same row.
        assert response.json()["timeSlot"]["status"] == "OPEN"

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["timeSlots"]] == [booking["id"]]
        assert available.json()["timeSlots"][0]["isBooked"] is False

    async def test_decline_releases_slot_with_same_id(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"status": "DECLINED"}, headers=landlord_headers
        )

        assert response.status_code == 200

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["timeSlots"]] == [booking["id"]]

    async def test_release_clears_candidate_and_meet_link(
        self, client, listing, landlord_headers, tenant_headers, session
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        await client.patch(
            f"{API}/time-slots/{booking['id']}",
            json={"status": "CANCELLED", "meetLink": "https://meet.example.com/x"},
            headers=landlord_headers,
        )

        from app.models.time_slot import TimeSlot

        row = await session.get(TimeSlot, booking["id"])
        await session.refresh(row)
        assert row.status == "OPEN"
        assert row.candidate_id is None
        assert row.meet_link is None

    async def test_candidate_cannot_reschedule(self, client, listing, landlord_headers, tenant_headers):
        """Landlord fields (start_time/type) are owner-only, even for the claiming candidate."""
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        new_start = datetime.now(timezone.utc) + timedelta(days=8)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"startTime": iso(new_start)}, headers=tenant_headers
        )

        assert response.status_code == 403
        assert response.json()["message"] == "You do not own this slot"


# --- Proposals ---


class TestProposeSlot:
    async def test_propose_creates_pending_slot(self, client, listing, tenant, tenant_headers, mock_external_services):
        response = await propose_slot(client, tenant_headers, listing["id"])

        assert response.status_code == 201, response.text
        body = response.json()["timeSlot"]
        assert body["status"] == "PENDING"
        assert body["candidateId"] == tenant["user"]["id"]
        assert body["landlordId"] == listing["landlordId"]
        assert body["landlordCreated"] is False
        assert body["type"] == "REMOTE"
        mock_external_services["booking_created"].assert_awaited_once()

    async def test_pending_proposal_visible_to_landlord_not_public(
        self, client, listing, landlord_headers, tenant_headers
    ):
        response = await propose_slot(client, tenant_headers, listing["id"])
        assert response.status_code == 201, response.text
        proposal = response.json()["timeSlot"]

        as_landlord = await client.get(f"{API}/time-slots/me", headers=landlord_headers)
        slots = as_landlord.json()["timeSlots"]
        assert [s["id"] for s in slots] == [proposal["id"]]
        assert slots[0]["status"] == "PENDING"

        as_tenant = await client.get(f"{API}/time-slots/me", headers=tenant_headers)
        assert [s["id"] for s in as_tenant.json()["timeSlots"]] == [proposal["id"]]

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert available.json()["timeSlots"] == []

    async def test_landlord_decline_deletes_proposed_row(self, client, listing, landlord_headers, tenant_headers):
        response = await propose_slot(client, tenant_headers, listing["id"])
        proposal = response.json()["timeSlot"]

        declined = await client.patch(
            f"{API}/time-slots/{proposal['id']}", json={"status": "DECLINED"}, headers=landlord_headers
        )
        assert declined.status_code == 200
        assert declined.json()["timeSlot"]["status"] == "DECLINED"

        # A proposed window was never real availability: declining removes it entirely.
        follow_up = await client.get(f"{API}/time-slots/{proposal['id']}", headers=landlord_headers)
        assert follow_up.status_code == 404

        slots = await client.get(f"{API}/time-slots/listing/{listing['id']}")
        assert slots.json()["timeSlots"] == []

    async def test_candidate_cancel_deletes_proposed_row(self, client, listing, landlord_headers, tenant_headers):
        response = await propose_slot(client, tenant_headers, listing["id"])
        proposal = response.json()["timeSlot"]

        cancelled = await client.patch(
            f"{API}/time-slots/{proposal['id']}", json={"status": "CANCELLED"}, headers=tenant_headers
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["timeSlot"]["status"] == "CANCELLED"

        follow_up = await client.get(f"{API}/time-slots/{proposal['id']}", headers=tenant_headers)
        assert follow_up.status_code == 404

    async def test_on_site_with_meet_link_rejected(self, client, listing, tenant_headers):
        response = await propose_slot(
            client, tenant_headers, listing["id"], type="ON_SITE", meet_link="https://meet.example.com/x"
        )

        assert response.status_code == 400

    async def test_cannot_propose_on_own_listing(self, client, listing, landlord_headers):
        response = await propose_slot(client, landlord_headers, listing["id"])

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot propose a time on your own listing"

    async def test_duplicate_start_time_rejected(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.post(
            f"{API}/time-slots/propose",
            json={"listingId": listing["id"], "startTime": slot["startTime"], "type": "REMOTE"},
            headers=tenant_headers,
        )

        assert response.status_code == 409
        assert response.json()["message"] == "A slot already exists at this time"

    async def test_propose_requires_authentication(self, client, listing):
        response = await client.post(
            f"{API}/time-slots/propose",
            json={"listingId": listing["id"], "startTime": "2027-01-01T10:00:00Z", "type": "REMOTE"},
        )

        assert response.status_code == 401

    async def test_propose_on_unknown_listing(self, client, tenant_headers):
        response = await propose_slot(client, tenant_headers, 999999)

        assert response.status_code == 404

    async def test_past_proposal_rejected(self, client, listing, tenant_headers):
        response = await propose_slot(client, tenant_headers, listing["id"], hours_from_now=-2)

        assert response.status_code == 400


# --- Availability windows ---


class TestCreateSlot:
    async def test_create_slot(self, client, listing, landlord_headers):
        response = await client.post(f"{API}/time-slots", json=slot_payload(listing["id"]), headers=landlord_headers)

        assert response.status_code == 201
        body = response.json()["timeSlot"]
        assert body["listingId"] == listing["id"]
        assert body["landlordId"] == listing["landlordId"]
        assert body["status"] == "OPEN"
        assert body["isBooked"] is False
        assert body["type"] == "REMOTE"

    async def test_create_on_site_slot(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/time-slots", json=slot_payload(listing["id"], type="ON_SITE"), headers=landlord_headers
        )

        assert response.status_code == 201
        assert response.json()["timeSlot"]["type"] == "ON_SITE"

    async def test_on_site_with_meet_link_rejected(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/time-slots",
            json=slot_payload(listing["id"], type="ON_SITE", meet_link="https://meet.example.com/x"),
            headers=landlord_headers,
        )

        assert response.status_code == 400

    async def test_type_is_required(self, client, listing, landlord_headers):
        payload = slot_payload(listing["id"])
        del payload["type"]

        response = await client.post(f"{API}/time-slots", json=payload, headers=landlord_headers)

        assert response.status_code == 422

    async def test_end_time_is_computed_as_start_plus_30_minutes(self, client, listing, landlord_headers):
        response = await client.post(f"{API}/time-slots", json=slot_payload(listing["id"]), headers=landlord_headers)

        assert response.status_code == 201
        body = response.json()["timeSlot"]
        start = datetime.fromisoformat(body["startTime"])
        end = datetime.fromisoformat(body["endTime"])
        assert end - start == timedelta(minutes=30)

    async def test_unknown_listing(self, client, landlord_headers):
        response = await client.post(f"{API}/time-slots", json=slot_payload(999999), headers=landlord_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Listing not found"

    async def test_non_owner_cannot_create_slot(self, client, listing):
        other = await sync_user(client, email="slot-landlord@example.com", role="LANDLORD")
        headers = headers_from_tokens(other)

        response = await client.post(f"{API}/time-slots", json=slot_payload(listing["id"]), headers=headers)

        assert response.status_code == 403
        assert response.json()["message"] == "You do not own this listing"

    async def test_tenant_cannot_create_slot(self, client, listing, tenant_headers):
        response = await client.post(f"{API}/time-slots", json=slot_payload(listing["id"]), headers=tenant_headers)

        assert response.status_code == 403


class TestGetSlots:
    async def test_available_slots_exclude_past_and_claimed(self, client, listing, landlord_headers, session):
        from app.models.time_slot import TimeSlot

        future = slot_payload(listing["id"], hours_from_now=48)
        past_payload = slot_payload(listing["id"], hours_from_now=-48)
        claimed_payload = slot_payload(listing["id"], hours_from_now=72)

        await client.post(f"{API}/time-slots", json=future, headers=landlord_headers)
        await client.post(f"{API}/time-slots", json=past_payload, headers=landlord_headers)
        claimed = await client.post(f"{API}/time-slots", json=claimed_payload, headers=landlord_headers)
        claimed_id = claimed.json()["timeSlot"]["id"]

        # Claim the slot directly in the DB (a booking is just a claimed slot now).
        slot = await session.get(TimeSlot, claimed_id)
        slot.status = "PENDING"
        await session.commit()

        response = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")

        assert response.status_code == 200
        slots = response.json()["timeSlots"]
        assert len(slots) == 1
        assert slots[0]["startTime"].startswith(future["startTime"][:19])

    async def test_all_slots_by_listing_is_booked_flips(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"], hours_from_now=24)
        await create_slot(client, landlord_headers, listing["id"], hours_from_now=48)

        response = await client.get(f"{API}/time-slots/listing/{listing['id']}")

        assert response.status_code == 200
        assert len(response.json()["timeSlots"]) == 2
        assert response.json()["timeSlots"][0]["isBooked"] is False

        await claim_slot(client, tenant_headers, slot["id"])

        claimed_view = await client.get(f"{API}/time-slots/listing/{listing['id']}")
        by_id = {s["id"]: s for s in claimed_view.json()["timeSlots"]}
        assert by_id[slot["id"]]["isBooked"] is True
        # The public listing view never exposes participants, even on claimed rows.
        assert by_id[slot["id"]]["candidateId"] is None

    async def test_get_slot_by_id(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.get(f"{API}/time-slots/{slot['id']}")

        assert response.status_code == 200
        assert response.json()["timeSlot"]["id"] == slot["id"]

    async def test_get_unknown_slot(self, client):
        response = await client.get(f"{API}/time-slots/999999")

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"


class TestUpdateSlot:
    async def test_update_start_time(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])
        new_start = datetime.now(timezone.utc) + timedelta(days=7)

        response = await client.patch(
            f"{API}/time-slots/{slot['id']}", json={"startTime": iso(new_start)}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["timeSlot"]["startTime"].startswith(new_start.strftime("%Y-%m-%dT"))

    async def test_update_type_on_open_slot(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.patch(
            f"{API}/time-slots/{slot['id']}", json={"type": "ON_SITE"}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["timeSlot"]["type"] == "ON_SITE"

    async def test_reschedule_claimed_slot_allowed(self, client, listing, landlord_headers, tenant_headers):
        """Rescheduling is safe on any status: a claim follows its slot's new time."""
        slot = await create_slot(client, landlord_headers, listing["id"])
        claimed = await claim_slot(client, tenant_headers, slot["id"])
        assert claimed.status_code == 201, claimed.text
        new_start = datetime.now(timezone.utc) + timedelta(days=8)

        response = await client.patch(
            f"{API}/time-slots/{slot['id']}", json={"startTime": iso(new_start)}, headers=landlord_headers
        )

        assert response.status_code == 200
        assert response.json()["timeSlot"]["startTime"].startswith(new_start.strftime("%Y-%m-%dT"))

        booking = await client.get(f"{API}/time-slots/{slot['id']}", headers=tenant_headers)
        assert booking.json()["timeSlot"]["startTime"].startswith(new_start.strftime("%Y-%m-%dT"))

    async def test_non_owner_cannot_update(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.patch(
            f"{API}/time-slots/{slot['id']}",
            json={"startTime": iso(datetime.now(timezone.utc))},
            headers=tenant_headers,
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"

    async def test_admin_can_update_any_slot(self, client, listing, landlord_headers, admin_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])
        new_start = datetime.now(timezone.utc) + timedelta(days=9)

        response = await client.patch(
            f"{API}/time-slots/{slot['id']}", json={"startTime": iso(new_start)}, headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["timeSlot"]["startTime"].startswith(new_start.strftime("%Y-%m-%dT"))

    async def test_type_locked_after_claim(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.patch(
            f"{API}/time-slots/{booking['id']}", json={"type": "ON_SITE"}, headers=landlord_headers
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Cannot change the type of a claimed slot"


# --- Deletion: hard delete for OPEN, release for claimed/proposed ---


class TestDelete:
    async def test_delete_open_slot(self, client, listing, landlord_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.delete(f"{API}/time-slots/{slot['id']}", headers=landlord_headers)

        assert response.status_code == 204
        follow_up = await client.get(f"{API}/time-slots/{slot['id']}")
        assert follow_up.status_code == 404

    async def test_non_owner_cannot_delete_open_slot(self, client, listing, landlord_headers, tenant_headers):
        slot = await create_slot(client, landlord_headers, listing["id"])

        response = await client.delete(f"{API}/time-slots/{slot['id']}", headers=tenant_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"

    async def test_delete_claimed_slot_releases_it(self, client, listing, landlord_headers, tenant_headers):
        """A claimed window is not silently destroyed: deleting it releases the slot."""
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.delete(f"{API}/time-slots/{booking['id']}", headers=landlord_headers)

        assert response.status_code == 204

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["timeSlots"]] == [booking["id"]]
        assert available.json()["timeSlots"][0]["isBooked"] is False

    async def test_delete_booking_releases_slot(
        self, client, listing, landlord_headers, tenant_headers, mock_external_services
    ):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)

        response = await client.delete(f"{API}/time-slots/{booking['id']}", headers=tenant_headers)

        assert response.status_code == 204
        mock_external_services["booking_cancelled"].assert_awaited_once()

        available = await client.get(f"{API}/time-slots/listing/{listing['id']}/available")
        assert [s["id"] for s in available.json()["timeSlots"]] == [booking["id"]]

    async def test_delete_proposed_booking_removes_row(self, client, listing, landlord_headers, tenant_headers):
        response = await propose_slot(client, tenant_headers, listing["id"])
        proposal = response.json()["timeSlot"]

        response = await client.delete(f"{API}/time-slots/{proposal['id']}", headers=tenant_headers)

        assert response.status_code == 204
        follow_up = await client.get(f"{API}/time-slots/{proposal['id']}", headers=tenant_headers)
        assert follow_up.status_code == 404

    async def test_outsider_cannot_delete(self, client, listing, landlord_headers, tenant_headers):
        booking = await create_booking(client, tenant_headers, listing["id"], landlord_headers)
        outsider = await sync_user(client, email="delete-outsider@example.com")
        outsider_headers = headers_from_tokens(outsider)

        response = await client.delete(f"{API}/time-slots/{booking['id']}", headers=outsider_headers)

        assert response.status_code == 404
        assert response.json()["message"] == "Time slot not found"
