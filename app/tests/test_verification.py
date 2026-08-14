import base64

from app.tests.conftest import API

# 1x1 transparent PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def upload_document(client, headers, listing_id, document_type="UTILITY_BILL", filename="bill.png"):
    response = await client.post(
        f"{API}/listings/{listing_id}/verification/documents",
        data={"documentType": document_type},
        files={"file": (filename, PNG_BYTES, "image/png")},
        headers=headers,
    )
    return response


class TestVerificationStatus:
    async def test_initial_status(self, client, listing, landlord_headers):
        response = await client.get(f"{API}/listings/{listing['id']}/verification", headers=landlord_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["verificationStatus"] == "PENDING"
        assert body["canResubmit"] is False
        assert body["documents"] == []
        assert body["history"] == []

    async def test_non_owner_cannot_view(self, client, listing, tenant_headers):
        response = await client.get(f"{API}/listings/{listing['id']}/verification", headers=tenant_headers)

        assert response.status_code == 403


class TestDocumentUpload:
    async def test_upload_document(self, client, listing, landlord_headers):
        response = await upload_document(client, landlord_headers, listing["id"])

        assert response.status_code == 201
        doc = response.json()["document"]
        assert doc["listingId"] == listing["id"]
        assert doc["documentType"] == "UTILITY_BILL"
        assert doc["fileName"] == "bill.png"
        assert doc["url"].startswith("http://localhost:9000/test-bucket/listings/")

    async def test_upload_rejects_disallowed_extension(self, client, listing, landlord_headers):
        response = await upload_document(client, landlord_headers, listing["id"], filename="bill.txt")

        assert response.status_code == 400
        assert "not allowed" in response.json()["message"]

    async def test_upload_rejects_empty_file(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/listings/{listing['id']}/verification/documents",
            data={"documentType": "UTILITY_BILL"},
            files={"file": ("empty.png", b"", "image/png")},
            headers=landlord_headers,
        )

        assert response.status_code == 400
        assert response.json()["message"] == "Empty file"

    async def test_documents_listing(self, client, listing, landlord_headers):
        await upload_document(client, landlord_headers, listing["id"])
        await upload_document(client, landlord_headers, listing["id"], document_type="TITLE_DEED")

        response = await client.get(f"{API}/listings/{listing['id']}/verification/documents", headers=landlord_headers)

        assert response.status_code == 200
        assert len(response.json()["documents"]) == 2

    async def test_delete_document(self, client, listing, landlord_headers):
        doc = (await upload_document(client, landlord_headers, listing["id"])).json()["document"]

        response = await client.delete(
            f"{API}/listings/{listing['id']}/verification/documents/{doc['id']}", headers=landlord_headers
        )

        assert response.status_code == 204
        remaining = await client.get(
            f"{API}/listings/{listing['id']}/verification/documents", headers=landlord_headers
        )
        assert remaining.json()["documents"] == []


class TestAdminReview:
    async def test_approve_listing(self, client, listing, admin_headers, landlord_headers):
        response = await client.post(
            f"{API}/admin/verifications/{listing['id']}/verification/review",
            json={"status": "APPROVED", "notes": "Documents verified"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Verification reviewed"
        assert body["verificationStatus"] == "APPROVED"

        status = await client.get(f"{API}/listings/{listing['id']}/verification", headers=landlord_headers)
        assert status.json()["verifiedAt"] is not None
        history = status.json()["history"]
        assert len(history) == 1
        assert history[0]["newStatus"] == "APPROVED"
        assert history[0]["previousStatus"] == "PENDING"

    async def test_reject_listing(self, client, listing, admin_headers, landlord_headers):
        await client.post(
            f"{API}/admin/verifications/{listing['id']}/verification/review",
            json={"status": "REJECTED", "notes": "Unclear documents"},
            headers=admin_headers,
        )

        status = await client.get(f"{API}/listings/{listing['id']}/verification", headers=landlord_headers)
        assert status.json()["verificationStatus"] == "REJECTED"
        assert status.json()["canResubmit"] is True

    async def test_resubmit_after_rejection(self, client, listing, admin_headers, landlord_headers):
        await client.post(
            f"{API}/admin/verifications/{listing['id']}/verification/review",
            json={"status": "REJECTED"},
            headers=admin_headers,
        )

        doc = await upload_document(client, landlord_headers, listing["id"])

        assert doc.status_code == 201
        status = await client.get(f"{API}/listings/{listing['id']}/verification", headers=landlord_headers)
        assert status.json()["verificationStatus"] == "PENDING"
        statuses = [h["newStatus"] for h in status.json()["history"]]
        assert statuses == ["REJECTED", "PENDING"]

    async def test_non_admin_cannot_review(self, client, listing, landlord_headers):
        response = await client.post(
            f"{API}/admin/verifications/{listing['id']}/verification/review",
            json={"status": "APPROVED"},
            headers=landlord_headers,
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    async def test_pending_listings(self, client, listing, landlord_headers, admin_headers):
        await upload_document(client, landlord_headers, listing["id"])

        response = await client.get(f"{API}/admin/verifications/pending", headers=admin_headers)

        assert response.status_code == 200
        pending = response.json()["listings"]
        assert [item["id"] for item in pending] == [listing["id"]]
        assert len(pending[0]["documents"]) == 1

    async def test_review_unknown_listing(self, client, admin_headers):
        response = await client.post(
            f"{API}/admin/verifications/999999/verification/review",
            json={"status": "APPROVED"},
            headers=admin_headers,
        )

        assert response.status_code == 404
