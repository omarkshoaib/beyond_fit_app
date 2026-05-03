# Beyond Fit — Privacy Policy

**Last updated: 2026-05-03**

This document explains what data Beyond Fit collects, how it is used, and the rights you have over it. The app is operated by **[Operator Name]** ("we", "us"). Contact: **[contact@beyondfit.app]**.

## 1. Data we collect

| Category | Specific items | Source | Why |
|---|---|---|---|
| **Account** | Email, name, hashed password (bcrypt), creation timestamp, email-verification timestamp | You | Authentication, account recovery |
| **Training profile** | Avatar (powerlifter / powerbuilder / general), training days per week, experience level, equipment, injuries / limitations, week number | You | Generating your personalised plan |
| **Workout history** | Generated plans, actual weight + RPE you log per main lift, check-in timestamps | You + the app | Auto-regulating future plans, showing progress charts |
| **Coach assignment** | Your assigned coach's identifier (if any), pending-approval queue records | Set by an admin | Coach review of your plans |
| **Operational logs** | IP address, user-agent, request paths, error stack traces | Automatic, server-side | Security, debugging, abuse prevention |

We do **not** collect: GPS location, contact list, photos, microphone, health-platform data (Apple Health / Google Fit), advertising identifiers.

## 2. How we use it

- **Provide the service.** Generate plans, deliver them, accept check-ins, surface progress.
- **Coach review.** If you have an assigned coach, your generated plans are visible to them in their dashboard until they approve or reject.
- **Account security.** Authenticate sign-in, rate-limit abuse, send password-reset and email-verification messages.
- **Improve the engine.** Aggregate, anonymised analysis of RPE/load adherence to refine the deterministic algorithm. Never sold or shared.

## 3. Sharing

We do **not** sell your data, share it with advertisers, or use it for any third-party marketing.

We share data only with:
- Your assigned coach (only your training profile + plans + check-ins for that coach).
- Our infrastructure providers under data-processing agreements: **[Hosting provider]**, **[SMTP provider]**, **[Crash-reporting provider, if any]**.
- Legal authorities when required by law (subpoena, court order).

## 4. Storage and retention

- Your data is stored in **[region — e.g. EU / US]** on encrypted disks.
- Account + training history are kept until you delete your account.
- Operational logs are kept for **30 days** then deleted.
- Crash reports are kept for **90 days**.

## 5. Your rights

You can:
- **Access** — export every record we have on you. Email `[contact@beyondfit.app]` with subject `Data export request`.
- **Correct** — edit your profile in-app or email us.
- **Delete** — wipe your account and all training history. Email us; we complete deletion within 30 days.
- **Object** — request we stop processing in any specific way.

If you are in the EU/UK, you have the rights under **GDPR / UK-GDPR**. If you are in California, the rights under **CCPA**.

Complaints may be filed with your local data-protection authority.

## 6. Security

- Passwords are hashed with **bcrypt**.
- Authentication uses signed JWTs (HS256). Access tokens expire in 24h, refresh tokens in 30 days, password-reset and email-verification tokens in 30 minutes / 48 hours respectively.
- Server is behind HTTPS in production. CORS is locked to the official frontend origin.
- We do not store full credit card details — payment processing (when added) will go through **[payment provider]**.

## 7. Children

Beyond Fit is intended for users **16 and older**. We do not knowingly collect data from anyone younger.

## 8. Changes to this policy

We will notify you in-app or by email at least 30 days before any material change takes effect.

## 9. Contact

**[contact@beyondfit.app]**

---

> Replace every `[bracketed placeholder]` with your real values before publishing.
