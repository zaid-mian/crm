# AdaptCRM - Backend-Frontend Integration Plan

This document maps the AdaptCRM (JTS + CRM) Django backend API resources to the React frontend views. It serves as the master technical blueprint for the integration team.

---

## Part 1: Authentication & Session Behavior

To support standard browser security patterns and prevent CORS/CSRF issues during integration, the backend and frontend adhere to the following authentication parameters:

### Core Configuration Settings
*   **`CORS_ALLOW_CREDENTIALS`**: Set to `True` in [settings.py](file:///e:/AdaptCRM/JWTCRM-Backend/config/settings.py#L139). This is required to allow the browser to accept and transmit cross-origin cookies.
*   **`CORS_ALLOWED_ORIGINS`**: Explicitly whitelists the React dev/production host origins:
    *   `http://localhost:3000`
    *   `http://127.0.0.1:3000`
    *   `http://localhost:5173` (Vite Default)
    *   `http://127.0.0.1:5173`
*   **`CSRF_TRUSTED_ORIGINS`**: Synchronized with the allowed origins to permit secure cookie-based CORS state mutations.

### Client-Side Connection Requirements
*   **`credentials: 'include'`**: React HTTP clients (Axios or Fetch) must explicitly set `withCredentials: true` or `credentials: 'include'` on every request to ensure the browser transmits the `sessionid` and `csrftoken` cookies.
*   **CSRF Header Transmission**: On state-changing operations (`POST`/`PUT`/`PATCH`/`DELETE`), React must extract the `csrftoken` cookie value and attach it to the `X-CSRFToken` request header.

---

## Part 2: Feature-by-Feature Endpoint Plan

### A. JTS Public Portal

#### Feature 1: Landing Page Catalog Listing
*   **Page name**: Products Catalog Landing
*   **Backend endpoint**: `/api/products/`
*   **HTTP method**: `GET`
*   **Authentication required?**: No
*   **CSRF required?**: No
*   **Response payload**: List of active products with basic catalog fields (Format A Success Envelope).

#### Feature 2: Product Detail & Pricing
*   **Page name**: Product Specification Page
*   **Backend endpoint**: `/api/products/<slug:slug>/`
*   **HTTP method**: `GET`
*   **Response payload**: Complete product payload including nested lists of modules and pricing plans.

---

### B. JTS Authentication & Password Reset

#### Feature 3: Customer Registration
*   **Page name**: Organization Sign-Up Form
*   **Backend endpoint**: `/api/register/`
*   **HTTP method**: `POST`
*   **Validation rules**: CNIC check (13 digits), phone check (11 digits, digits only), email uniqueness.

#### Feature 4: Platform Login
*   **Page name**: User Login
*   **Backend endpoint**: `/api/login/`
*   **HTTP method**: `POST`
*   **Response payload**: Returns standard success envelope with user metadata (Format A).

#### Feature 5: REST Password Reset Confirm
*   **Page name**: Password Reset Recovery Form
*   **Backend endpoint**: `/api/auth/reset-password/confirm/`
*   **HTTP method**: `POST`
*   **Request payload**:
    ```json
    {
      "uidb64": "...",
      "token": "...",
      "new_password": "...",
      "confirm_password": "..."
    }
    ```
*   **Status**: Fully Implemented (REST-ready, returns Format A envelope).

---

### C. JTS Catalog Administration (REST CRUD)

#### Feature 6: Catalog CRUD Management
*   **Backend endpoints**:
    *   Products: `/api/admin/products/`
    *   Modules: `/api/admin/modules/`
    *   Pricing Plans: `/api/admin/pricing-plans/`
    *   Plan Modules: `/api/admin/plan-modules/`
    *   Discounts: `/api/admin/discounts/`
*   **HTTP methods**: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`
*   **Permissions**: Restricted to Platform Administrators (`is_staff` / `is_superuser`). GET methods are publicly readable.
*   **Status**: Fully Implemented (all endpoints return Standard Format A success/error envelopes).

---

## Part 3: Readiness & Risk Analysis

All critical backend risks identified in the initial audit have been resolved:

1.  **CORS/CSRF Vulnerabilities**: Secured via explicit whitelists and DRF session handlers.
2.  **HTML Password Reset**: Replaced with clean REST endpoints.
3.  **Cross-Tenant Data Exposure**: Resolved via robust database-level organization isolation queries.
4.  **Admin CRUD Operations**: Fully supported via Catalog Admin REST APIs.
5.  **Response Shapes**: Envelope consistency is 100% aligned.
