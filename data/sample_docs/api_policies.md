# API Policies

## Rate Limiting

Each API key is limited to 1,000 requests per minute. Requests beyond this limit receive a
429 response with a `Retry-After` header.

## Versioning

The API is versioned via the URL path (`/v1/`, `/v2/`). A version is supported for at least
12 months after a newer version is released, and deprecation notices are sent 90 days in
advance via the developer newsletter.

## Authentication

All requests must include a bearer token issued via the `/auth/token` endpoint. Tokens
expire after 24 hours and must be refreshed using the associated refresh token.
