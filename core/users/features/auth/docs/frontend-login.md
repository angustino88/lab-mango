# Microsoft login: frontend integration guide

For the web frontend (`@azure/msal-react` 5.x / `@azure/msal-browser` 5.x, auth code + PKCE). Backend
behaviour is specified in [spec.md](spec.md) section 3.2.

## What changed (2026-11-12)

| Before | Now |
|---|---|
| `POST /api/aad-login/challenge` returned `nonce` and `csrf_token` | **Removed.** The browser creates the nonce itself; `GET /api/csrf-token` returns the CSRF token |
| `POST /api/aad-login` body: `{ id_token }` | Body: `{ id_token, nonce_secret }` |

Why: behind the Router the frontend signs in with Microsoft **before** it knows which department backend
serves the user, so no backend can issue the nonce in advance. Without the Router the same code works
unchanged; only the base URL differs.

## Steps

1. **Before Microsoft sign-in**, create a secret, store it, and derive the nonce:

   ```ts
   function base64url(bytes: Uint8Array): string {
     let text = "";
     bytes.forEach((byte) => (text += String.fromCharCode(byte)));
     return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
   }

   export async function createLoginNonce(): Promise<string> {
     const secret = base64url(crypto.getRandomValues(new Uint8Array(32))); // 43 characters
     sessionStorage.setItem("labmango.loginNonceSecret", secret);
     const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
     return base64url(new Uint8Array(digest));
   }
   ```

2. **Sign in with MSAL**, passing that nonce (replaces the call to `/api/aad-login/challenge`):

   ```ts
   const nonce = await createLoginNonce();
   await instance.loginRedirect({ scopes: ["openid", "profile", "offline_access"], nonce });
   ```

3. **After the redirect**, get the ID token, a CSRF token, and log in to the backend:

   ```ts
   const result = await instance.handleRedirectPromise(); // or the msal-react equivalent
   const secret = sessionStorage.getItem("labmango.loginNonceSecret");
   sessionStorage.removeItem("labmango.loginNonceSecret");
   if (!result?.idToken || !secret) throw new Error("Login was not completed");

   const base = apiBaseUrl; // "/api" today; the Router-resolved prefix later
   const csrf = await fetch(`${base}/csrf-token`, { credentials: "include" }).then((r) => r.json());
   const response = await fetch(`${base}/aad-login`, {
     method: "POST",
     credentials: "include",
     headers: { "Content-Type": "application/json", "X-CSRFToken": csrf.data.csrf_token },
     body: JSON.stringify({ id_token: result.idToken, nonce_secret: secret }),
   });
   ```

4. Keep using the CSRF token from step 3 for `POST /api/refresh-token` and `POST /api/logout`. Staff
   logins return a rotated `csrf_token` in the login response; use that one afterwards.

## Rules the backend enforces

- `nonce_secret`: 43–128 characters of `A–Z a–z 0–9 - _` (the code above produces 43).
- The ID token's `nonce` must equal base64url(SHA-256(`nonce_secret`)), without `=` padding.
- The ID token must have been issued less than 10 minutes ago: send it right after the redirect.
- Each ID token logs in **once**; a repeated request returns `401 invalid_sso_token`. Start a new
  sign-in (new secret) to log in again.
- Never send the secret anywhere except `POST /aad-login` (not to the Router, not to logs).
