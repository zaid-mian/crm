# AdaptCRM — Unified Multi-Tenant CRM, Job Tracking & Standalone Billing Engine

[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.7-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/Django%20REST%20Framework-3.17.1-red.svg)](https://www.django-rest-framework.org/)
[![License](https://img.shields.io/badge/License-Proprietary-purple.svg)]()
[![Build & Tests](https://img.shields.io/badge/Tests-122%2F122%20Passing%20(100%25)-brightgreen.svg)]()

AdaptCRM is an enterprise-grade, multi-tenant Customer Relationship Management (CRM) platform seamlessly integrated with an operational **Job Tracking System (JTS)** and a decoupled **Standalone Commercial Billing & Subscription Engine**.

---

## 📑 Table of Contents
- [1. Master System Architecture Diagrams](#1-master-system-architecture-diagrams)
  - [1.1 Complete Platform Ecosystem Architecture](#11-complete-platform-ecosystem-architecture)
  - [1.2 CRM Sales Pipeline & Deal Conversion Architecture](#12-crm-sales-pipeline--deal-conversion-architecture)
  - [1.3 Standalone Commercial Billing Engine Architecture](#13-standalone-commercial-billing-engine-architecture)
- [2. Core Platform Capabilities](#2-core-platform-capabilities)
- [3. Application Modules & Architecture](#3-application-modules--architecture)
- [4. Centralized Dynamic RBAC & 5 Granular Billing Resources](#4-centralized-dynamic-rbac--5-granular-billing-resources)
- [5. Financial Integrity & Architectural Invariants](#5-financial-integrity--architectural-invariants)
- [6. API Surface & Endpoint Reference](#6-api-surface--endpoint-reference)
- [7. Installation & Quickstart](#7-installation--quickstart)
- [8. Testing & Verification](#8-testing--verification)

---

## 1. Master System Architecture Diagrams

### 1.1 Complete Platform Ecosystem Architecture
This diagram illustrates the full ecosystem uniting **Multi-Tenant Foundation & RBAC**, the **JTS Service Portal**, the **CRM Sales Pipeline**, and the **Standalone Commercial Billing Engine**:

```mermaid
flowchart TD
    %% Section 1: Governance & Security
    subgraph S1 ["1. MULTI-TENANT & SECURITY FOUNDATION"]
        TENANT["Organization Tenant Isolation<br/>(Strict Multi-Tenancy per Organization)"]
        RBAC["Centralized Dynamic RBAC<br/>(3-Tier Scopes: ALL / OWN / NONE & 5 Billing Resources)"]
        AUTH["Unified Authentication & Session Router<br/>(JWT Auth, Direct CRM vs JTS Identity)"]
    end

    %% Section 2: JTS Client Platform
    subgraph S2 ["2. JTS CLIENT PORTAL & JOB TRACKING"]
        JTS_PUB["Public Catalog & Landing<br/>(Service Details & Online Registration)"]
        JTS_USER["Client Portal (User Dashboard)<br/>(Service Applications & Document Uploads)"]
        JTS_ADMIN["JTS Admin Fulfillment<br/>(Application Review & Job Operations)"]
        JTS_PUB --> JTS_USER
        JTS_USER <--> JTS_ADMIN
    end

    %% Section 3: CRM Sales Pipeline
    subgraph S3 ["3. CRM SALES & RELATIONSHIP ENGINE"]
        LEADS["Inbound Leads Engine<br/>(Website, Campaigns, Direct Outreach)"]
        PIPE["Dynamic Kanban Pipeline<br/>(Standard & Custom Pipelines)"]
        TRIAD["Auto-Linked Business Profiles<br/>(Company, Contact, Opportunity)"]
        WON["Closed Won Opportunity<br/>(Deal Terms & Scope Finalized)"]
        LEADS --> PIPE
        PIPE -->|Qualify & Convert| TRIAD
        TRIAD -->|Negotiation & Closing| WON
    end

    %% Section 4: Standalone Billing Engine
    subgraph S4 ["4. STANDALONE COMMERCIAL BILLING ENGINE"]
        BCUST["Billing Customer Account<br/>(Currency, Tax ID, Wallet Balance)"]
        BSUB["Subscription Agreement<br/>(Locked Pricing Snapshot & Terms)"]
        BINV["Immutable Posted Invoice<br/>(Sequential INV Number & PDF)"]
        BPAY["Payments Ledger & Allocations<br/>(Decoupled Cash & Settle to PAID)"]
        SAFE["Safeguards: Dunning & Adjustments<br/>(Retries: Day 3/7/14 & Credit Notes)"]
        BCUST --> BSUB
        BSUB -->|Billing Cycle| BINV
        BINV -->|Settlement| BPAY
        BINV -.->|Payment Recovery| SAFE
        SAFE -.->|Recovered Funds| BPAY
    end

    %% Section 5: Support & Executive Intelligence
    subgraph S5 ["5. POST-SALES SUPPORT & EXECUTIVE INTELLIGENCE"]
        SUPP["Support Ticketing System<br/>(Client Inquiries & SLA Resolution)"]
        UREP["Sales User Reporting<br/>(Rep Productivity & Win Rates)"]
        BREP["Revenue Analytics Dashboard<br/>(Live MRR, ARR & Waterfall Growth)"]
    end

    %% Inter-System Bridges (Node-to-Node)
    TENANT --> JTS_PUB
    RBAC --> PIPE
    RBAC --> BSUB
    AUTH --> SUPP
    
    JTS_USER -.->|Service Inquiries| LEADS
    WON -->|Convert to Subscription| BCUST
    TRIAD -.->|Ongoing Relationship| SUPP
    PIPE -.->|Sales Data| UREP
    BINV -.->|Financial Ledger| BREP

    %% Styling
    classDef darkBox fill:#0f172a,stroke:#6366f1,stroke-width:2px,color:#ffffff;
    classDef jtsBox fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f;
    classDef crmBox fill:#f0f9ff,stroke:#0284c7,stroke-width:2px,color:#0c4a6e;
    classDef billBox fill:#fdf4ff,stroke:#a855f7,stroke-width:2px,color:#581c87;
    classDef intelBox fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d;

    class S1,TENANT,RBAC,AUTH darkBox;
    class S2,JTS_PUB,JTS_USER,JTS_ADMIN jtsBox;
    class S3,LEADS,PIPE,TRIAD,WON crmBox;
    class S4,BCUST,BSUB,BINV,BPAY,SAFE billBox;
    class S5,SUPP,UREP,BREP intelBox;
```

---

### 1.2 CRM Sales Pipeline & Deal Conversion Architecture
This diagram outlines the complete front-office sales workflow from inbound prospect ingestion through Kanban deal qualification and automatic record linking:

```mermaid
flowchart TD
    subgraph Ingestion ["1. INBOUND INTAKE CHANNELS"]
        IN_WEB["Website Forms"]
        IN_CAMP["Marketing Campaigns"]
        IN_DIR["Direct Sales Outreach"]
    end

    subgraph LeadsModule ["2. LEADS MANAGEMENT & QUALIFICATION"]
        LEAD_REC["Lead Record<br/>• Contact Info & Company Name<br/>• Priority (High / Medium / Low)<br/>• Assigned Sales Representative"]
        LEAD_DRAWER["Lead Details Drawer<br/>• 360-Degree Contact View<br/>• Activity & Timeline History"]
    end

    subgraph PipelineEngine ["3. PIPELINE KANBAN ENGINE"]
        PIPE_SEL["Pipeline Selector<br/>(Standard Default vs Custom Configured Pipelines)"]
        ST_NEW["Stage 1: New<br/>(Initial Inbound)"]
        ST_CONT["Stage 2: Contacted<br/>(Outreach Initiated)"]
        ST_CONF["Stage 3: Confirm<br/>(Requirements Gathered)"]
    end

    subgraph ConversionEngine ["4. UNIFIED CONVERSION ENGINE"]
        MODAL["Lead Conversion Modal<br/>(Auto-Linked Records Summary)"]
        COMP["Company Profile<br/>(Corporate Account)"]
        CONT["Contact Profile<br/>(Key Stakeholder)"]
        OPP["Opportunity Deal<br/>(Deal Value & Timeline)"]
    end

    subgraph ClosingEngine ["5. DEAL NEGOTIATION & CLOSING"]
        ST_PROP["Stage 4: Proposal<br/>(Quote Delivered)"]
        ST_NEG["Stage 5: Negotiation<br/>(Contract Terms Finalized)"]
        ST_WON["Stage 6: Closed Won<br/>(Deal Agreement Secured)"]
        DRAWER["Won Opportunity Drawer<br/>(Convert to Subscription Action)"]
    end

    Ingestion --> LEAD_REC
    LEAD_REC --- LEAD_DRAWER
    LEAD_REC --> PIPE_SEL
    PIPE_SEL --> ST_NEW
    ST_NEW --> ST_CONT
    ST_CONT --> ST_CONF
    ST_CONF -->|Trigger Conversion| MODAL
    MODAL --> COMP
    MODAL --> CONT
    MODAL --> OPP
    OPP --> ST_PROP
    ST_PROP --> ST_NEG
    ST_NEG --> ST_WON
    ST_WON --> DRAWER

    classDef inStyle fill:#f8fafc,stroke:#94a3b8,stroke-width:2px,color:#0f172a;
    classDef leadStyle fill:#eff6ff,stroke:#3b82f6,stroke-width:2px,color:#1e3a8a;
    classDef pipeStyle fill:#f0f9ff,stroke:#0284c7,stroke-width:2px,color:#0c4a6e;
    classDef convStyle fill:#fdf4ff,stroke:#c026d3,stroke-width:2px,color:#701a75;
    classDef wonStyle fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46;

    class IN_WEB,IN_CAMP,IN_DIR inStyle;
    class LEAD_REC,LEAD_DRAWER leadStyle;
    class PIPE_SEL,ST_NEW,ST_CONT,ST_CONF pipeStyle;
    class MODAL,COMP,CONT,OPP convStyle;
    class ST_PROP,ST_NEG,ST_WON,DRAWER wonStyle;
```

---

### 1.3 Standalone Commercial Billing Engine Architecture
This diagram depicts the decoupled commercial billing engine, showcasing pricing snapshots, automated invoicing, decoupled payments, dunning recovery, and revenue intelligence:

```mermaid
flowchart TD
    subgraph CustomerLayer ["1. COMMERCIAL CUSTOMER IDENTITY"]
        BCUST["Billing Customer Account<br/>• Multi-Tenant Organization Scope<br/>• Currency (USD / PKR) & Tax Identifiers<br/>• Default Terms (Net 0 / Net 30) & Credit Wallet"]
    end

    subgraph SubscriptionLayer ["2. SUBSCRIPTION LIFECYCLE & PRICING SNAPSHOTS"]
        SUB["Subscription Contract (SUB-XXXXX)<br/>• Monthly / Yearly Billing Term Cadence<br/>• Auto-Renewal & Term Advance Scheduling<br/>• State Machine: LIVE / PAST_DUE / PAUSED / CANCELLED"]
        ITEMS["Subscription Items & Add-ons<br/>• Immutable Unit Price Snapshot (Frozen at Agreement)<br/>• Catalog Price Changes Do Not Alter Active Subscriptions"]
    end

    subgraph InvoicingLayer ["3. IDEMPOTENT INVOICING & DOCUMENT ENGINE"]
        INV["Posted Invoice (INV-YYYY-XXXXX)<br/>• Deterministic Idempotency Key (No Duplicate Bills)<br/>• Itemized Subtotals, Taxes & Discounts<br/>• Automated Branded PDF Generation via ReportLab"]
    end

    subgraph SettlementLayer ["4. PAYMENTS & DOUBLE-ENTRY ALLOCATIONS"]
        PAY["Decoupled Payment (PAY-XXXXX)<br/>• Stripe Tokenized Gateway & Bank Transfers<br/>• Independent Cash Tracking"]
        ALLOC["Payment Allocation Ledger<br/>• Binds Payments to Invoices<br/>• Automatic Settlement to PAID Status"]
    end

    subgraph RecoveryLayer ["5. DUNNING RECOVERY & FINANCIAL ADJUSTMENTS"]
        DUN["Automated Dunning Engine<br/>• Smart Retries: Day 3, Day 7, Day 14<br/>• Past-Due & Unpaid Lifecycle Alerts"]
        ADJ["Formal Financial Adjustments<br/>• Credit Notes & Debit Notes<br/>• Negative Invoice Lines Strictly Prohibited"]
        AUDIT["Immutable Audit Trail<br/>• SubscriptionAuditLog & ChangeLog<br/>• Double-Entry Balance Verification"]
    end

    subgraph AnalyticsLayer ["6. REVENUE INTELLIGENCE & RBAC"]
        MRR["Revenue Analytics Dashboard<br/>• Real-Time MRR, ARR & ARPU<br/>• Net MRR Movement Waterfall (New / Expansion / Churn)"]
        RBAC["5 Granular RBAC Permissions<br/>(Analytics, Customers, Subscriptions, Invoices, Payments)"]
    end

    BCUST -->|Provisions Contract| SUB
    SUB --- ITEMS
    SUB -->|Periodic Billing Cycle| INV
    INV -->|Requires Settlement| ALLOC
    PAY --> ALLOC
    ALLOC -->|Settles Invoice| INV
    INV -.->|Failed Payment| DUN
    DUN -.->|Recovers Funds| PAY
    INV -.->|Correction / Refund| ADJ
    SUB -.->|Auditable Event| AUDIT
    INV -.->|Auditable Event| AUDIT
    ALLOC -.->|Auditable Event| AUDIT
    AUDIT -->|Aggregates into| MRR
    RBAC -.->|Governs Access to| BCUST
    RBAC -.->|Governs Access to| SUB
    RBAC -.->|Governs Access to| INV
    RBAC -.->|Governs Access to| PAY

    classDef custStyle fill:#fdf4ff,stroke:#c026d3,stroke-width:2px,color:#701a75;
    classDef subStyle fill:#f0f9ff,stroke:#0284c7,stroke-width:2px,color:#075985;
    classDef invStyle fill:#f8fafc,stroke:#475569,stroke-width:2px,color:#0f172a;
    classDef payStyle fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d;
    classDef recStyle fill:#fffbeb,stroke:#f59e0b,stroke-width:2px,color:#78350f;
    classDef revStyle fill:#eff6ff,stroke:#3b82f6,stroke-width:2px,color:#1e3a8a;

    class CustomerLayer,BCUST custStyle;
    class SubscriptionLayer,SUB,ITEMS subStyle;
    class InvoicingLayer,INV invStyle;
    class SettlementLayer,PAY,ALLOC payStyle;
    class RecoveryLayer,DUN,ADJ,AUDIT recStyle;
    class AnalyticsLayer,MRR,RBAC revStyle;
```

---

## 2. Core Platform Capabilities

1. **Multi-Tenancy & Data Isolation (`accounts.Organization`)**: Every database query is strictly filtered by tenant organization for authenticated non-staff users.
2. **Centralized Dynamic RBAC (`roles`)**: Complete permission matrix based on **Resource**, **Action** (`VIEW`, `CREATE`, `EDIT`, `DELETE`, `EXPORT`, `ASSIGN`), and **Scope** (`ALL`, `OWN`, `NONE`).
3. **Decoupled Commercial Architecture**: CRM manages relationships, pipelines, and deals; Standalone Billing manages subscriptions, invoices, and payments without importing CRM domain apps.
4. **Frozen Pricing Snapshots**: Subscription item prices are frozen at creation (`SubscriptionItem.unit_price`), ensuring catalog updates never alter existing contracts.
5. **Legally Immutable Invoicing**: Once posted, invoice line items and totals cannot be altered; corrections require formal `CreditNote` or `DebitNote` records.
6. **Automated Dunning Recovery**: Smart retry schedule on **Day 3, Day 7, and Day 14** automatically recovers failed subscription payments.
7. **Executive Real-Time Analytics**: Live computation of Monthly Recurring Revenue (MRR), Annual Recurring Revenue (ARR), ARPU, and MRR Waterfall growth.

---

## 3. Application Modules & Architecture

```
JWTCRM-Backend/
├── accounts/           ──► Multi-tenant Organization, User profiles, CNIC verification, JWT Auth
├── billing/            ──► Standalone Billing Engine (Customers, Subscriptions, Invoices, Payments, Dunning, Analytics)
├── catalog/            ──► Master catalog of products, services, pricing plans, and feedback
├── companies/          ──► Corporate accounts linked to contacts and opportunities
├── config/             ──► Project settings, middleware, and master URL routing
├── contacts/           ──► Individual stakeholder records
├── dashboard/          ──► Sales dashboards, pipeline funnel, team leaderboards, and PDF reporting
├── leads/              ──► Inbound prospect capture, qualification, and communication timeline
├── opportunities/      ──► Commercial deals, value scoping, and "Convert to Subscription" action
├── payments/           ──► Legacy CRM milestone payments (/api/payments/)
├── pipeline/           ──► Dynamic Standard & Custom Kanban pipelines and stage reordering
├── roles/              ──► Centralized dynamic RBAC, custom resources registry, and permission engine
└── support/            ──► Customer ticketing, issue management, and resolution workflows
```

---

## 4. Centralized Dynamic RBAC & 5 Granular Billing Resources

The RBAC system defines three permission scopes:
- **`ALL`**: User can access all organization records.
- **`OWN`**: User can access only records assigned to or created by them (`metadata__created_by_id=user.id`).
- **`NONE`**: Access blocked across both API and UI.

### The 5 Granular Billing Resources
Billing access is split into 5 independently configurable resources:
1. `billing_analytics` — Revenue Analytics dashboard (MRR, ARR, Waterfall).
2. `billing_customers` — Commercial customer account records and credit wallet.
3. `billing_subscriptions` — Subscription agreements, plan items, and lifecycle actions.
4. `billing_invoices` — Posted invoice records, line item calculations, and PDF generation.
5. `billing_payments` — Payments ledger and double-entry invoice allocations.

---

## 5. Financial Integrity & Architectural Invariants

- **Decimal Precision**: All monetary values use `Decimal` with `'0.01'` precision. Floating-point arithmetic is strictly forbidden.
- **Decoupled Payments**: Payments represent actual collected funds and are stored independently from invoices.
- **Double-Entry Allocation**: The binding between payments and invoices exists exclusively through `PaymentAllocation` records.
- **Deterministic Idempotency**: Invoicing runs enforce unique deterministic keys (`inv_sub_<id>_period_<date>`) to prevent duplicate billing.
- **Server-Side Authoritative Math**: All calculations (taxes, discounts, prorations, allocations) occur strictly on the backend.

---

## 6. API Surface & Endpoint Reference

### Authentication & Tenant Accounts
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/login/` | Authenticate user and issue session token |
| `GET` | `/api/me/` | Retrieve authenticated user profile, roles, and permissions |
| `POST` | `/api/register/` | Register new organization and owner account |
| `POST` | `/api/logout/` | Terminate user session |

### CRM Core Modules
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET / POST` | `/api/leads/` | List and create inbound leads |
| `GET / POST` | `/api/pipeline/` | Manage pipelines and Kanban stages |
| `GET / POST` | `/api/companies/` | List and create company profiles |
| `GET / POST` | `/api/contacts/` | List and create contact profiles |
| `GET / POST` | `/api/opportunities/` | Manage deals and sales stages |
| `POST` | `/api/opportunities/<id>/convert-to-subscription/` | Provision commercial subscription from won deal |
| `GET` | `/api/dashboard/summary/` | Retrieve company-wide sales KPIs |

### Standalone Commercial Billing (`/api/v1/billing/`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET / POST` | `/api/v1/billing/customers/` | Manage commercial billing customers |
| `GET / POST` | `/api/v1/billing/subscriptions/` | Manage subscriptions and terms |
| `POST` | `/api/v1/billing/subscriptions/<id>/transition/` | State machine transition (Activate, Pause, Cancel, Renew) |
| `POST` | `/api/v1/billing/subscriptions/<id>/amend/` | Subscription plan amendment & proration preview |
| `GET / POST` | `/api/v1/billing/invoices/` | List and generate posted invoices |
| `GET` | `/api/v1/billing/invoices/<id>/pdf/` | Stream branded PDF invoice document |
| `GET / POST` | `/api/v1/billing/payments/` | Record collected payments |
| `POST` | `/api/v1/billing/payments/<id>/allocate/` | Allocate payment to open invoices |
| `GET / POST` | `/api/v1/billing/credit-notes/` | Manage credit note balance adjustments |
| `GET` | `/api/v1/billing/analytics/overview/` | Real-time MRR, ARR, and subscriber metrics |
| `GET` | `/api/v1/billing/analytics/mrr-movement/` | Net MRR waterfall growth breakdown |
| `POST` | `/api/v1/billing/webhooks/stripe/` | Process asynchronous Stripe webhook events |

---

## 7. Installation & Quickstart

### Prerequisites
- **Python 3.12+** (Python 3.14 compatible)
- **SQLite3** (default) or **PostgreSQL 15+**

### Step-by-Step Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/zaid-mian/crm.git
   cd crm
   ```

2. **Create & Activate Virtual Environment**:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a local `.env` file in the root directory:
   ```env
   SECRET_KEY=your-secure-django-secret-key
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   STRIPE_SECRET_KEY=sk_test_your_key
   STRIPE_PUBLISHABLE_KEY=pk_test_your_key
   STRIPE_WEBHOOK_SECRET=whsec_your_secret
   ```

5. **Apply Database Migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create an Administrator Account**:
   ```bash
   python manage.py createsuperuser
   ```

7. **Run the Development Server**:
   ```bash
   python manage.py runserver 8000
   ```
   The backend API will be live at `http://localhost:8000/`.

---

## 8. Testing & Verification

The repository includes a comprehensive unit and integration test suite covering RBAC, Multi-Tenancy, and all 16 Billing phases.

```bash
# Run system and migration integrity checks
python manage.py check
python manage.py makemigrations --check

# Run Centralized RBAC and Granular Billing Permission tests
python manage.py test roles.tests billing.tests.test_rbac_independence

# Run Core Standalone Billing test suite
python manage.py test billing.tests.test_customers billing.tests.test_subscriptions billing.tests.test_invoicing billing.tests.test_payments billing.tests.test_credit_notes billing.tests.test_analytics
```

**Verification Results:** All 122 targeted tests pass with a 100% success rate.
