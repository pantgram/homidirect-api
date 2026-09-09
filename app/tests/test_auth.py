from app.tests.conftest import (
    API,
    VALID_PASSWORD,
    auth_headers_for,
    create_db_user,
    headers_from_tokens,
    login_user,
    register_user,
)


class TestRegister:
    async def test_register_success(self, client):
        body = await register_user(client, email="new@example.com", role="LANDLORD")

        assert body["user"]["email"] == "new@example.com"
        assert body["user"]["firstName"] == "Test"
        assert body["user"]["lastName"] == "User"
        assert body["user"]["role"] == "LANDLORD"
        assert body["user"]["id"] > 0
        assert body["user"]["createdAt"]
        assert body["token"]["accessToken"]
        assert body["token"]["refreshToken"]

    async def test_register_duplicate_email(self, client):
        await register_user(client, email="dup@example.com")
        response = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Other",
                "lastName": "User",
                "email": "dup@example.com",
                "password": VALID_PASSWORD,
                "role": "TENANT",
            },
        )

        assert response.status_code == 409
        assert response.json() == {"error": "ConflictError", "message": "Email already registered"}

    async def test_register_weak_password(self, client):
        response = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Weak",
                "lastName": "Pass",
                "email": "weak@example.com",
                "password": "password",
                "role": "TENANT",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "Validation Error"
        details = {d["path"] for d in body["details"]}
        assert "password" in details

    async def test_register_short_password(self, client):
        response = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Short",
                "lastName": "Pass",
                "email": "short@example.com",
                "password": "Ab1",
                "role": "TENANT",
            },
        )

        assert response.status_code == 422

    async def test_register_invalid_role(self, client):
        response = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Bad",
                "lastName": "Role",
                "email": "badrole@example.com",
                "password": VALID_PASSWORD,
                "role": "SUPERUSER",
            },
        )

        assert response.status_code == 422

    async def test_register_invalid_email(self, client):
        response = await client.post(
            f"{API}/auth/register",
            json={
                "firstName": "Bad",
                "lastName": "Email",
                "email": "not-an-email",
                "password": VALID_PASSWORD,
                "role": "TENANT",
            },
        )

        assert response.status_code == 422


class TestLogin:
    async def test_login_success(self, client):
        await register_user(client, email="login@example.com")
        body = await login_user(client, "login@example.com", VALID_PASSWORD)

        assert body["token"]["accessToken"]
        assert body["token"]["refreshToken"]

    async def test_login_wrong_password(self, client):
        await register_user(client, email="login2@example.com")
        response = await client.post(
            f"{API}/auth/login", json={"email": "login2@example.com", "password": "WrongPass1"}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password"

    async def test_login_unknown_email(self, client):
        response = await client.post(
            f"{API}/auth/login", json={"email": "ghost@example.com", "password": VALID_PASSWORD}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password"

    async def test_login_google_account_without_password(self, client, session):
        user = await create_db_user(session, email="google@example.com")
        user.password = None
        await session.commit()

        response = await client.post(
            f"{API}/auth/login", json={"email": "google@example.com", "password": VALID_PASSWORD}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password"

    async def test_login_failures_are_indistinguishable(self, client):
        await register_user(client, email="timing@example.com")

        unknown = await client.post(
            f"{API}/auth/login", json={"email": "ghost2@example.com", "password": VALID_PASSWORD}
        )
        wrong = await client.post(
            f"{API}/auth/login", json={"email": "timing@example.com", "password": "WrongPass1"}
        )
        google_style = await client.post(
            f"{API}/auth/login", json={"email": "timing@example.com", "password": ""}
        )

        assert unknown.status_code == wrong.status_code == google_style.status_code == 401
        assert unknown.json() == wrong.json() == google_style.json()


class TestRefresh:
    async def test_refresh_returns_new_tokens(self, client):
        registered = await register_user(client, email="refresh@example.com")

        response = await client.post(
            f"{API}/auth/refresh", json={"refreshToken": registered["token"]["refreshToken"]}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["tokens"]["accessToken"]
        assert body["tokens"]["refreshToken"]

    async def test_refresh_with_invalid_token(self, client):
        response = await client.post(f"{API}/auth/refresh", json={"refreshToken": "not-a-jwt"})

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid refresh token"

    async def test_refresh_revoked_after_logout(self, client):
        registered = await register_user(client, email="revoke@example.com")
        headers = headers_from_tokens(registered["token"])
        refresh_token = registered["token"]["refreshToken"]

        logout = await client.post(f"{API}/auth/logout", headers=headers)
        assert logout.status_code == 200

        response = await client.post(f"{API}/auth/refresh", json={"refreshToken": refresh_token})
        assert response.status_code == 401
        assert response.json()["message"] == "Token has been revoked"

    async def test_refresh_banned_user(self, client, session):
        from app.dependencies.auth import create_refresh_token

        user = await create_db_user(session, email="banned-refresh@example.com")
        user.status = "BANNED"
        await session.commit()
        refresh = create_refresh_token({"id": user.id, "email": user.email, "token_version": 0})

        response = await client.post(f"{API}/auth/refresh", json={"refreshToken": refresh})

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid refresh token"

    async def test_refresh_rejects_access_token(self, client):
        registered = await register_user(client, email="refresh-access@example.com")

        response = await client.post(
            f"{API}/auth/refresh", json={"refreshToken": registered["token"]["accessToken"]}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid token type"


class TestLogout:
    async def test_logout_revokes_access_token(self, client):
        registered = await register_user(client, email="logout@example.com")
        headers = headers_from_tokens(registered["token"])

        response = await client.post(f"{API}/auth/logout", headers=headers)
        assert response.status_code == 200
        assert response.json()["message"] == "Logged out successfully"

        me = await client.get(f"{API}/users/me", headers=headers)
        assert me.status_code == 401
        assert me.json()["message"] == "Token has been revoked"

    async def test_logout_requires_authentication(self, client):
        response = await client.post(f"{API}/auth/logout")

        assert response.status_code == 401


class TestPasswordReset:
    async def test_forgot_password_sends_reset_email(self, client, mock_external_services):
        await register_user(client, email="forgot@example.com")

        response = await client.post(f"{API}/auth/forgot-password", json={"email": "forgot@example.com"})

        assert response.status_code == 200
        assert "reset link has been sent" in response.json()["message"]
        mock_external_services["password_reset"].assert_awaited_once()
        args = mock_external_services["password_reset"].await_args.args
        assert args[0] == "forgot@example.com"
        reset_token = args[1]
        assert reset_token

        # Token stored in DB is hashed, never the raw token
        reset = await client.post(
            f"{API}/auth/reset-password", json={"token": reset_token, "password": "NewPassword123"}
        )
        assert reset.status_code == 200

        await login_user(client, "forgot@example.com", "NewPassword123")

    async def test_forgot_password_unknown_email_is_generic(self, client, mock_external_services):
        response = await client.post(f"{API}/auth/forgot-password", json={"email": "unknown@example.com"})

        assert response.status_code == 200
        assert "reset link has been sent" in response.json()["message"]
        mock_external_services["password_reset"].assert_not_awaited()

    async def test_reset_password_invalid_token(self, client):
        response = await client.post(
            f"{API}/auth/reset-password", json={"token": "bogus", "password": "NewPassword123"}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid or expired reset token"

    async def test_reset_password_revokes_old_tokens(self, client, mock_external_services):
        registered = await register_user(client, email="revoke-reset@example.com")
        old_headers = headers_from_tokens(registered["token"])

        await client.post(f"{API}/auth/forgot-password", json={"email": "revoke-reset@example.com"})
        reset_token = mock_external_services["password_reset"].await_args.args[1]
        response = await client.post(
            f"{API}/auth/reset-password", json={"token": reset_token, "password": "NewPassword123"}
        )
        assert response.status_code == 200

        me = await client.get(f"{API}/users/me", headers=old_headers)
        assert me.status_code == 401

    async def test_reset_password_rejects_weak_password(self, client):
        response = await client.post(
            f"{API}/auth/reset-password", json={"token": "whatever", "password": "weak"}
        )

        assert response.status_code == 422


class TestCurrentUserAuth:
    async def test_access_token_without_header(self, client):
        response = await client.get(f"{API}/users/me")

        assert response.status_code == 401

    async def test_access_token_malformed(self, client):
        response = await client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 401

    async def test_refresh_token_rejected_as_bearer(self, client):
        registered = await register_user(client, email="bearer-refresh@example.com")

        response = await client.get(
            f"{API}/users/me",
            headers={"Authorization": f"Bearer {registered['token']['refreshToken']}"},
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid token type"

    async def test_legacy_token_without_type_claim_rejected(self, client, session):
        from jose import jwt

        from app.config.settings import settings

        user = await create_db_user(session, email="legacy-token@example.com", role="TENANT")
        legacy = jwt.encode(
            {"id": user.id, "email": user.email, "token_version": user.token_version},
            settings.jwt_secret,
            algorithm="HS256",
        )

        response = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {legacy}"})

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid token type"

    async def test_refresh_token_treated_as_anonymous_for_optional_user(self, client):
        registered = await register_user(client, email="optional-user@example.com")

        response = await client.get(
            f"{API}/listings/search",
            headers={"Authorization": f"Bearer {registered['token']['refreshToken']}"},
        )

        assert response.status_code == 200

    async def test_banned_user_forbidden(self, client, session):
        user = await create_db_user(session, email="banned@example.com", status="ACTIVE")
        user.status = "BANNED"
        await session.commit()

        response = await client.get(f"{API}/users/me", headers=auth_headers_for(user))

        assert response.status_code == 403
        assert "banned" in response.json()["message"]
