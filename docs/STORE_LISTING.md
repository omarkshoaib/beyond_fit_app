# App Store + Play Store Listing Copy

Drop-in metadata for the iOS App Store and Google Play submissions.

---

## App name

**Beyond Fit** *(30-char limit on Play Store; this fits.)*

## Short description (Play Store, 80 chars)

> Deterministic strength coach. No fluff. Adapts to how hard your weeks felt.

## Subtitle (App Store, 30 chars)

> Strength coach that adapts.

## Long description

```
Beyond Fit is a deterministic strength coach in your pocket.

Every week, the app generates a personalised plan from your profile —
training days, experience level, equipment, injuries, and the RPE +
weight you logged from the last week's main lifts. The engine is pure
math, not opinion: same inputs always produce the same plan.

WHAT'S IN A PLAN
• 2–6 training days per week, fitted to your schedule
• Main compound, secondary compound, and isolation slots per day
• Warmup ramps with real percentages of your working set
• Auto-regulation: overshot RPE last week? loads drop. undershot? loads rise.
• Deload week every 5 weeks — built in, never optional

COACH OPTIONAL
Assign yourself a coach (or skip it) and they review every plan in their
dashboard before it lands in your home screen. Reject, send feedback,
regenerate — all in-app.

PROGRESS YOU CAN SEE
RPE trend + load trend charts pull straight from your check-ins.

PRIVACY
We do not sell your data, ever. No ads. Your training history is yours.
See our privacy policy at beyondfit.app/privacy

NOT MEDICAL ADVICE
Talk to your doctor before starting any programme.
```

## Keywords (App Store, 100 chars total, comma-separated)

```
strength,workout,powerlifting,bodybuilding,RPE,coach,gym,training,deload,hypertrophy,powerbuilder
```

## Category

**Primary:** Health & Fitness
**Secondary (App Store only):** Sports

## Age rating

- **Apple:** 12+ (Infrequent/Mild Medical/Treatment Information)
- **Google:** PEGI 12 / Teen — references to physical exertion + fitness terminology

## Required URLs

| Field | URL |
|---|---|
| Privacy policy | `https://beyondfit.app/privacy` *(host `docs/PRIVACY_POLICY.md` rendered)* |
| Support | `https://beyondfit.app/support` *(or email `support@beyondfit.app`)* |
| Marketing site | `https://beyondfit.app` |

## Screenshots required

| Device | Resolution | Count |
|---|---|---|
| iPhone 6.9" (iPhone 16 Pro Max) | 1290 × 2796 | 3–10 |
| iPhone 6.7" (iPhone 15 Plus) | 1290 × 2796 | 3–10 |
| iPad 13" | 2048 × 2732 | 3–10 |
| Android phone | 1080 × 1920+ | 2–8 |
| Android 7" tablet | 1200 × 1920+ | 1–8 (optional) |
| Android 10" tablet | 1600 × 2560+ | 1–8 (optional) |

**Recommended captures:**
1. Onboarding step 1 (Goal picker)
2. Today's session card with Start Workout CTA
3. Workout screen with sets/reps/weight/RPE
4. Progress charts
5. Coach dashboard (if pitching coach feature)
6. Plan under-review state (shows the human-in-the-loop angle)

## What's new (release notes)

```
Initial release.
- Personalised weekly plans
- RPE-based auto-regulation
- Optional coach review
- Progress charts
```

## Apple-specific

**App Privacy answers** (Data Used to Track You / Linked to You / Not Linked):

| Data | Linked? | Tracking? | Purpose |
|---|---|---|---|
| Email address | Linked | No | Account, account recovery |
| Name | Linked | No | Personalisation |
| User ID | Linked | No | Account |
| Health & fitness — workout history, RPE | Linked | No | App functionality |
| Diagnostics — crash logs, performance | Linked | No | Bug fixing |
| Identifiers — IP address (server logs) | Not linked | No | Security |

## Google Play-specific

**Data safety section:**
- Personal info: name, email — collected, encrypted in transit, encrypted at rest, you can request deletion.
- Fitness info: workout history, RPE, weight lifted — collected, encrypted in transit and at rest.
- App activity: crash logs — collected for app diagnostics.
- No data shared with third parties for advertising / analytics.

**Content rating questionnaire:** Health & Fitness app, no graphic violence / gambling / alcohol / mature themes.

---

> Replace `beyondfit.app` with your real domain and `Operator Name` placeholders in PRIVACY_POLICY.md / TERMS.md before submission.
