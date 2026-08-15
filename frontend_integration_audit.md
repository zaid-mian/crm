# AdaptCRM - Frontend Integration Audit

This audit document serves as the single technical reference for integrating the upcoming React frontend with the merged Django-based JTS + CRM backend. 

---

## 1. Backend Architecture & Technologies

* **Python & Framework**: Python 3 / Django 6.0 / Django REST Framework (DRF) 3.15.
* **Database**: SQLite (`db.sqlite3` in base workspace path).
* **Cross-Origin Resource Sharing (CORS)**:
  * Configured in [settings.py](file:///e:/AdaptCRM/JWTCRM-Backend/config/settings.py#L138-L139) with `CORS_ALLOW_ALL_ORIGINS = True` and `CORS_ALLOW_CREDENTIALS = True`.
  * Middleware `corsheaders.middleware.CorsMiddleware` is registered.
* **Exceptions & Errors**:
  * Centralized exception handler configured at [exceptions.py](file:///e:/AdaptCRM/JWTCRM-Backend/leads/utils/exceptions.py).
  * Automatically wraps generic DRF serializer and permission errors into a standard `{ "success": false, "message": "...", "errors": { ... } }` envelope.

---

## 2. Authentication & Session Management

### Registration Flow
* **API Endpoint**: `POST /api/register/` (routed to `PlatformRegisterView` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L26-L37)).
* **Request Payload**:
  ```json
  {
    "email": "user@example.com",
    "password": "secure_password",
    "first_name": "John",
    "last_name": "Doe",
    "company_name": "Acme Corp",
    "cnic": "1234567890123",
    "phone_number": "+923001234567",
    "country": "Pakistan",
    "address": "Office Suite 4B, Plaza 9"
  }
  ```
* **Validations**:
  * **Email**: Required, normalized to lowercase, checked for global uniqueness.
  * **Password**: Required, minimum length of 6 characters.
  * **CNIC**: Checked against regex pattern `^\d{5}-?\d{7}-?\d{1}$` (13 digits, optional dashes allowed).
  * **Phone Number**: Normalized by stripping spaces/dashes and checked against pattern `^\+?\d{11,15}$`.
* **State Upon Registration**:
  * A `User` record is created with `is_active=False`.
  * An `Organization` record is created with `is_active=False`.
  * An `OwnerProfile` links the user and organization.
  * A `RegistrationRequest` is created in `'pending'` status.

### Login Flow
* **API Endpoint**: `POST /api/login/` (routed to `LoginView` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L40-L95)).
* **Mechanism**: Django Session-based Authentication. 
  * Authenticates using either `username` or `email` (strip-lowercased before authentication).
  * On success, sets standard session cookies (`sessionid` and `csrftoken`).
* **Error Handling**:
  * If account is inactive (`is_active=False`) and has a pending `RegistrationRequest`, returns `403 Forbidden` with: `{"success": false, "message": "Your registration is pending admin approval. Please try again later."}`.
  * If rejected, returns: `{"success": false, "message": "Your registration was rejected. Reason: <reason>"}`.
  * Invalid credentials return `401 Unauthorized`.

### Session Verification & Current User
* **API Endpoint**: `GET /api/me/` (routed to `MeView` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L98-L135)).
* **Response Payload**:
  ```json
  {
    "success": true,
    "message": "User details retrieved successfully",
    "data": {
      "id": 1,
      "username": "user@example.com",
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "is_staff": false,
      "is_superuser": false,
      "profile": {
        "cnic": "1234567890123",
        "phone_number": "+923001234567",
        "country": "Pakistan",
        "address": "Office Suite 4B, Plaza 9",
        "organization": {
          "id": 1,
          "name": "Acme Corp",
          "logo": null,
          "is_active": true
        }
      }
    }
  }
  ```

### Password Actions
* **Change Password**: `POST /api/auth/change-password/` (routed to `ChangePasswordView` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L171-L199)). Enforces current password confirmation, password strength validation, and updates active session.
* **Forgot Password**: `POST /api/auth/forgot-password/` (routed to `ForgotPasswordView` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L201-L249)). Sends email via Django Console backend with dynamic reset link.
* **Password Reset Confirm**: `GET/POST /api/auth/reset-password/<uidb64>/<token>/` and `/api/auth/reset-password-complete/` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L251-L258).
  > [!WARNING]
  > These two endpoints are HTML template-based Django Views (`PasswordResetConfirmView`, `PasswordResetCompleteView`) rather than REST endpoints, requiring Django-rendered pages or redirection of the client browser.

### CSRF Protection
* Standard Django CSRF middleware is active. React must read the `csrftoken` cookie and transmit it via the `X-CSRFToken` request header for all state-changing operations (POST, PUT, PATCH, DELETE).

---

## 3. JTS Public Portal

Endpoints intended to populate public-facing landing pages, pricing plans, and feedback forums.

* **Product List**: `GET /api/products/` in [catalog/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/catalog/views.py#L13-L19). Returns a list of active products.
* **Product Detail**: `GET /api/products/<slug:slug>/` in [catalog/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/catalog/views.py#L22-L34). Returns product information along with nested **modules** and **pricing_plans** (with active discounts computed at runtime).
* **Service List**: `GET /api/services/` in [catalog/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/catalog/views.py#L37-L43).
* **Service Detail**: `GET /api/services/<slug:slug>/` in [catalog/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/catalog/views.py#L46-L58).
* **Submit Feedback**: `POST /api/products/<slug>/feedback/` and `POST /api/services/<slug>/feedback/` in [catalog/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/catalog/views.py#L61-L167).
  * Enforces authenticated user.
  * Checks validation: Rating must be an integer between 1 and 5.
  * Validation helper `can_user_review` determines if user has owned/subscribed to the item before allowing feedback.

---

## 4. JTS Administration (Platform Admin)

Endpoints utilized by platform administrators (`is_staff` or `is_superuser`) to manage registrations and audit users.

* **Registration Approvals List**: `GET /api/admin/registrations/` in [admin.py (accounts)](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/admin.py#L16-L27). Returns all registrations in `pending` status.
* **Approve Registration**: `POST /api/admin/registrations/<int:pk>/approve/` in [admin.py (accounts)](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/admin.py#L29-L63).
  * Marks status as `'approved'`, sets user `is_active = True`, and organization `is_active = True`.
  * Automatically fires `registration_approved` signal to provision the tenant CRM user profile.
* **Reject Registration**: `POST /api/admin/registrations/<int:pk>/reject/` in [admin.py (accounts)](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/admin.py#L65-L105).
  * Requires a JSON body: `{ "reason": "Reason details" }`.
  * Marks request as `'rejected'` and emails user.
* **User List**: `GET /api/admin/users/` in [admin.py (accounts)](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/admin.py#L108-L173). Support query parameters `?search=` and `?ordering=`. Returns list of users, their organization, platform role, and status.
* **Organization List**: `GET /api/admin/organizations/` in [admin.py (accounts)](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/admin.py#L176-L183).
  * Returns list of organizations.

> [!IMPORTANT]
> **Django Admin vs React Admin Syncing**: Django Admin displays all organizations in a simple database query, while the React approvals screen is populated using `/api/admin/registrations/` or `/api/admin/organizations/`. To sync, the frontend approvals tab must correctly represent the organization's registration state or `is_active` parameter.
> 
> **Missing JTS Admin REST CRUD Endpoints**:
> The backend lacks API endpoints for administrators to manage Products, Modules, Pricing Plans, Plan Modules, or Discounts. Currently, these must be configured via the standard Django Admin interface at `/admin/`.

---

## 5. JTS User Dashboard & Account Operations

* **Profile Update**: `PATCH /api/me/` in [auth.py](file:///e:/AdaptCRM/JWTCRM-Backend/accounts/views/auth.py#L136-L160).
  * Modifies first name, last name, phone number, country, and address.
* **Helpdesk Support Ticket List/Create**: `GET/POST /api/support/tickets/` in [support/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/support/views.py#L32-L85).
  * Regular users can only see their own tickets, while support staff can see all.
  * Creation automatically associates the ticket with the logged-in user's tenant `Organization`.
* **Ticket Actions**:
  * `GET /api/support/tickets/<ticket_number>/`: Detail view including replies thread.
  * `POST /api/support/tickets/<ticket_number>/reply/`: Submits replies.
  * `POST /api/support/tickets/<ticket_number>/status/`: Updates ticket status (resolved, closed).
  * `POST /api/support/tickets/<ticket_number>/assign/`: Assigns ticket to support personnel (Staff only).
* **Missing Views**:
  * No standalone JTS user billing/subscription portal endpoint exists to purchase or select plans.
  * No JTS-specific user dashboard endpoint is available (only support ticket counts are tracked).

---

## 6. CRM Module Administration (CRM Admin)

Endpoints for users with `ADMIN` classification (`UserProfile.user_type == 'ADMIN'`) to set up system resources, pipelines, and roles.

* **List / Create Roles**: `GET/POST /api/roles/` in [roles/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/roles/views.py#L36-L75). Protected for Administrators only.
* **Delete Roles**: `DELETE /api/roles/<id>/`. Restricts deletion of system-defined roles (`is_system=True`) or roles that are currently assigned to active users.
* **CRM Resources List**: `GET /api/roles/resources/` in [roles/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/roles/views.py#L77-L82). Returns list of CRM modules dynamically auto-discovered by the CRM registry scanner.
* **Get / Set Role Permissions Matrix**: `GET/PUT /api/roles/<id>/permissions/` in [roles/views.py](file:///e:/AdaptCRM/JWTCRM-Backend/roles/views.py#L84-L129). Overwrites permissions for a role in a single bulk operation and invalidates the cached permissions of associated users.

---

## 7. CRM Operations (CRM User)

Standard CRM module views scoped dynamically according to user assignment rules.

### Leads
* **Endpoints**: `GET/POST/PUT/PATCH /api/leads/` in [views/lead.py (leads)](file:///e:/AdaptCRM/JWTCRM-Backend/leads/views/lead.py#L50-L161).
* **Search & Filters**:
  * Fields: `?full_name=`, `?phone=`, `?email=`, `?company_name=`.
  * Search: `?search=` maps to `full_name`, `phone`, `email`, and `company_name`.
  * Ordering: `?ordering=` support fields `created_at`, `priority`, `status`, `updated_at`.
* **Lead Conversion**: `POST /api/leads/<id>/convert/` in [views/lead.py (leads)](file:///e:/AdaptCRM/JWTCRM-Backend/leads/views/lead.py#L184-L209).
  * Automatically creates a `Company`, a `Contact`, and an active `Opportunity` in `Qualification` pipeline stage. Transferred fields are deduplicated.
* **Custom Actions**:
  * `POST /api/leads/<id>/assign/`: Assigns lead to a salesperson.
  * `POST /api/leads/<id>/lost/`: Marks lead as lost (requires `lost_reason` and optional `lost_notes`).
  * `POST /api/leads/<id>/contacted/`: Increments contact attempts and updates stage.
  * `GET /api/leads/stats/`: Returns summary statistics grouped by status.

### Companies
* **Endpoints**: `GET/POST/PUT/PATCH/DELETE /api/companies/` in [views/company.py (companies)](file:///e:/AdaptCRM/JWTCRM-Backend/companies/views/company.py#L45-L142).
* **Filters**: `?type=`, `?rating=`, `?industry=`, `?search=`.
* **Delete Protection**: Triggering `DELETE` on a company with associated contacts or opportunities will return a `400 Bad Request` citing related records.

### Contacts
* **Endpoints**: `GET/POST/PUT/PATCH/DELETE /api/contacts/` in [views/contact.py (contacts)](file:///e:/AdaptCRM/JWTCRM-Backend/contacts/views/contact.py#L44-L151).
* **Delete Logic**: Employs soft deletes (`is_deleted = True`) to prevent cascade deletions.

### Opportunities
* **Endpoints**: `GET/PUT/PATCH /api/opportunities/` in [views/opportunity.py (opportunities)](file:///e:/AdaptCRM/JWTCRM-Backend/opportunities/views/opportunity.py#L44-L140).
  * > [!IMPORTANT]
    > **No Create or Delete APIs**: Opportunities cannot be created directly via the API (no `POST` or `DELETE` endpoints). They are generated solely via Lead conversion, and closed opportunities are locked.
* **Sequential Transitions**:
  * Custom Action `POST /api/opportunities/<id>/change-stage/` shifts deals through stages sequentially (e.g., Qualification $\rightarrow$ Discovery $\rightarrow$ Proposal). Direct skips or updates from closed stages are restricted.

### Payments & Invoicing
* **Endpoints**: `GET/POST/PUT/PATCH/DELETE /api/payments/` in [views/payment.py (payments)](file:///e:/AdaptCRM/JWTCRM-Backend/payments/views/payment.py#L48-L156).
* **Custom Actions**:
  * `POST /api/payments/invoice/`: Generates an invoice for an opportunity.
  * `GET /api/payments/<id>/invoice/`: Renders/downloads Invoice PDF.
  * `GET /api/payments/<id>/receipt/`: Prints payment transaction receipts.

### CRM Dashboard Metrics
* **Endpoints**:
  * `GET /api/dashboard/summary/`: Total pipelines, won revenue, overdue collections.
  * `GET /api/dashboard/pipeline/`: Entity stage counts for Kanban boards.
  * `GET /api/dashboard/activity/`: Unified activities feed.
  * `GET /api/dashboard/charts/`: Data distributions (lead sources, payment summaries).
* > [!WARNING]
  > All CRM Dashboard endpoints use Django cache. Cache timeout is set to 60 seconds.

---

## 8. Role & Permission Matrix

Access control is governed by two central components:
1. **Dynamic Guard (`DynamicCRMPermission` in [permissions.py (roles)](file:///e:/AdaptCRM/JWTCRM-Backend/roles/permissions.py#L41-L121))**:
   * Evaluates if a user's assigned role matches the required action scope for a CRM resource.
2. **Query Scoping Filter (`get_scoped_queryset` in [permissions.py (roles)](file:///e:/AdaptCRM/JWTCRM-Backend/roles/permissions.py#L11-L38))**:
   * Dynamically appends `.filter(assigned_salesperson=user)` to SQL queries for standard CRM users.

| Platform Role | View Scope | Write Scope | Assignment Access |
| :--- | :--- | :--- | :--- |
| **Administrator** | `ALL` (Sees all tenant records) | `ALL` (Modifies any record) | Can assign records to any salesperson |
| **Manager** | `ALL` (Sees all pipeline records) | `ALL` (Adjusts stages, comments) | Can assign/reassign |
| **Salesperson** | `OWN` (Only records where salesperson matches) | `OWN` (Updates assigned cards) | None (Auto-assigned to self) |

---

## 9. Tenant Isolation & Integration Mechanism

### JTS $\rightarrow$ CRM Integration Handshake
When an admin approves an organization registration, the database transaction triggers a Django Signal receiver (`provision_crm_workspace` in [receivers.py (leads)](file:///e:/AdaptCRM/JWTCRM-Backend/leads/receivers.py#L6-L22)):
1. Checks if a CRM `UserProfile` exists for the approved user.
2. Creates or updates the `UserProfile` setting `user_type = 'ADMIN'` and mapping them to the system role `Administrator`.
3. This grants the organization owner access to CRM modules.

### The Tenant Isolation Deficit
> [!CAUTION]
> **No Organization Column on CRM Models**:
> The database models for **Leads, Contacts, Companies, Opportunities, Pipelines, and Payments do NOT have an `organization` or `tenant` foreign key column**.
> 
> **How isolation currently functions**:
> * Standard `Salesperson` users are restricted via their `OWN` permission scope filter (e.g., they only see cards where `assigned_salesperson == request.user`).
> * `Admin` and `Manager` roles default to `ALL` scope, meaning they bypass assignment filters. Because there is no organization filter on the querysets, **an Admin user from Org A will see all CRM records of Org B if their scope resolves to `ALL`**.
> * Multi-tenant segregation is only implemented on the **Support Ticket** model (which has an `organization` foreign key). CRM records are stored globally.

---

## 10. Response Envelopes & Serialization Inconsistencies

DRF views utilize a mix of custom success helpers and raw serializer payloads, requiring client-side API integrations to handle variations:

### Format A: Standard Enveloped Response
Used by Accounts registration, login, profile operations, support tickets, and CRM entities (Leads, Contacts, Companies, Opportunities, Payments).
* **Success Format**:
  ```json
  {
    "success": true,
    "message": "Leads listed successfully.",
    "data": {
      "pagination": { "page": 1, "page_size": 20, "total_pages": 1, "total_items": 3 },
      "results": [ ... ]
    }
  }
  ```
* **Error Format**:
  ```json
  {
    "success": false,
    "message": "Validation failed.",
    "errors": {
      "phone_number": [ "Phone number must be 11-15 digits, optionally starting with +." ]
    }
  }
  ```

### Format B: Raw DRF Responses
Used by **Dashboard** endpoints (`/api/dashboard/summary/`, etc.) and **Roles** administration (`/api/roles/`, `/api/roles/resources/`, etc.).
* **Response Format**:
  ```json
  [
    { "id": 1, "name": "Administrator", "is_system": true },
    { "id": 2, "name": "Salesperson", "is_system": true }
  ]
  ```
  *(Not wrapped in a `success`, `message`, or `data` dictionary).*

### Format C: Raw Delete Validation Error
Used by `CompanyViewSet.destroy` under `ProtectedError` (line 141 of [views/company.py (companies)](file:///e:/AdaptCRM/JWTCRM-Backend/companies/views/company.py#L141)).
* **Response Format**:
  ```json
  { "detail": "Cannot delete company because it has related contacts..." }
  ```
  *(Bypasses custom exception handler and returns a raw DRF detail response).*

---

## 11. Frontend Integration Risks

1. **CSRF Verification Failures**: Standard AJAX headers won't suffice for React if credentials aren't passed. React must configure axios/fetch to include credentials (`credentials: 'include'`) and read cookies.
2. **Missing CRM Isolation**: Organization administrators will see other organizations' records if their role permission scope is set to `ALL`. React developers must be cautious about displaying records without user verification.
3. **Template Redirects on Password Reset**: Forgot-password emails links point to the server-side Django HTML views. React will need to proxy or override these views if a complete single-page application experience is desired.
4. **Endpoint Payload Discrepancies**: Integrating developers must handle the distinction between enveloped endpoints (e.g. CRM modules) and raw list/dict endpoints (e.g. dashboard stats and roles matrix).

---

## 12. Page $\rightarrow$ API Route Mapping

| Frontend View / Action | HTTP Method | API Path | Access / Role Required | Response Format |
| :--- | :--- | :--- | :--- | :--- |
| **User Sign Up** | POST | `/api/register/` | Public | Enveloped Success/Error |
| **User Sign In** | POST | `/api/login/` | Public | Enveloped Success/Error |
| **Change Password** | POST | `/api/auth/change-password/` | Authenticated | Enveloped Success/Error |
| **Forgot Password Request** | POST | `/api/auth/forgot-password/` | Public | Enveloped Success |
| **Fetch Profile / Tenant** | GET | `/api/me/` | Authenticated | Enveloped Success |
| **Update User Profile** | PATCH | `/api/me/` | Authenticated | Enveloped Success |
| **User Logout** | POST | `/api/logout/` | Authenticated | Enveloped Success |
| **JTS Catalog (Products)** | GET | `/api/products/` | Public | Enveloped Success |
| **JTS Product Details** | GET | `/api/products/<slug>/` | Public | Enveloped Success |
| **JTS Support Tickets** | GET/POST | `/api/support/tickets/` | Authenticated | Enveloped Success |
| **Ticket Add Reply** | POST | `/api/support/tickets/<num>/reply/` | Authenticated | Enveloped Success |
| **Admin List Approvals** | GET | `/api/admin/registrations/` | Platform Staff / Admin | Enveloped Success |
| **Approve Tenant Org** | POST | `/api/admin/registrations/<id>/approve/` | Platform Staff / Admin | Enveloped Success |
| **Reject Tenant Org** | POST | `/api/admin/registrations/<id>/reject/` | Platform Staff / Admin | Enveloped Success |
| **List Admin Users** | GET | `/api/admin/users/` | Platform Staff / Admin | Enveloped Success |
| **List Admin Orgs** | GET | `/api/admin/organizations/` | Platform Staff / Admin | Enveloped Success |
| **CRM Dashboard Stats** | GET | `/api/dashboard/summary/` | Authenticated | **Raw DRF dict** |
| **CRM Kanban Stages** | GET | `/api/dashboard/pipeline/` | Authenticated | **Raw DRF list** |
| **List Roles Matrix** | GET | `/api/roles/` | CRM Admin | **Raw DRF list** |
| **Set Permissions Matrix** | PUT | `/api/roles/<id>/permissions/` | CRM Admin | **Raw DRF list** |
| **List / Create Leads** | GET/POST | `/api/leads/` | Authenticated (scoped) | Enveloped Success |
| **Convert Lead to Deal** | POST | `/api/leads/<id>/convert/` | Authenticated (scoped) | Enveloped Success |
| **List / Detail Companies** | GET | `/api/companies/` | Authenticated (scoped) | Enveloped Success |
| **List / Detail Contacts** | GET | `/api/contacts/` | Authenticated (scoped) | Enveloped Success |
| **Update Opportunity** | PUT/PATCH | `/api/opportunities/<id>/` | Authenticated (scoped) | Enveloped Success |
| **Change Opportunity Stage** | POST | `/api/opportunities/<id>/change-stage/` | Authenticated (scoped) | Enveloped Success |
| **Record Payments / Invoice**| POST | `/api/payments/invoice/` | Authenticated (scoped) | Enveloped Success |
| **Render Invoice PDF** | GET | `/api/payments/<id>/invoice/` | Authenticated (scoped) | Raw PDF Binary Stream |

---

## 13. Integration Readiness Classifications

* **Platform Authentication & Registrations**: `READY`
  * Fully implemented, validates formats, manages states, and provisions default administrator workspace correctly.
* **JTS Public Landing & Catalog APIs**: `READY`
  * Exposes products, services, nested structures, active discounts, and feedback modules with appropriate permission filters.
* **JTS Administration APIs**: `PARTIAL`
  * Approvals, rejections, user rosters, and organizations list views are available.
  * **Gap**: Dashboard stats, product catalog management, and plan setup APIs are missing; Django Admin must be used.
* **JTS Support Helpdesk**: `READY`
  * Implemented with tenant scoping (`organization` column) and assignment flows.
* **CRM Administrative configuration (RBAC)**: `READY`
  * Role CRUD and bulk permission matrices are functional.
  * **Caution**: Response payloads are returned raw (un-enveloped).
* **CRM Operations (Leads, Companies, Contacts, Opportunities, Payments)**: `READY`
  * Comprehensive services manage lead qualification, deal conversion, and invoices.
  * **Gap**: Opportunity creation and deletion are locked out of direct APIs. Soft deletes are used on contacts.
* **CRM Dashboard metrics**: `READY`
  * Cached summaries, pipeline stage funnels, activities feed, and chart data are available.
  * **Caution**: Return payloads are un-enveloped raw dictionaries.
* **Multi-Tenant Data Segregation**: `BLOCKED`
  * **Status**: Critical architectural deficit. CRM data (Leads, Companies, Contacts, Opportunities, Payments) lacks database-level organization isolation fields. Standard tenant isolation is based solely on assignment filters, exposing data cross-over risks for high-privilege roles. Requires structural schema modification prior to multi-tenant release.
