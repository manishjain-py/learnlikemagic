# Owner Setup Guide — Login & Profile Feature

Everything **you** need to configure before the login/profile code will work. The codebase handles the integration, but these external services require manual setup.

---

## 1. AWS Cognito User Pool

This is the core auth service. It manages user accounts, passwords, OTPs, and tokens.

### Steps

1. Open **AWS Console** → search **Cognito** → **Create user pool**

2. **Sign-in experience**
   - Authentication providers: Cognito user pool
   - Sign-in options: check **Email** and **Phone number**
   - Click Next

3. **Security requirements**
   - Password policy: Minimum 8 characters (match the PRD)
   - MFA: **Optional MFA** → select **SMS message**
   - User account recovery: check **Email**
   - Click Next

4. **Sign-up experience**
   - Self-registration: **Enabled**
   - Cognito-assisted verification: **Enabled**
   - Attributes to verify: **Send email message, verify email address**
   - Required attributes: **email**, **name**
   - Click Next

5. **Message delivery** (see sections 2 and 3 below for details)
   - Email: start with **Send email with Cognito** (free, 50/day limit for dev)
   - SMS: select **Send SMS messages with Amazon SNS**
   - Click Next

6. **App integration**
   - User pool name: `learnlikemagic-users`
   - Hosted authentication pages: **Use Cognito's hosted UI** (or skip if using custom UI only)
   - Domain: choose a prefix like `learnlikemagic` → gives you `learnlikemagic.auth.us-east-1.amazoncognito.com`
   - App client name: `learnlikemagic-web`
   - Client secret: **Don't generate a client secret** (SPA/public client)
   - Callback URL: `http://localhost:3000/auth/callback` (add production URL later)
   - Sign-out URL: `http://localhost:3000/login`
   - OAuth 2.0 grant types: **Authorization code grant**
   - OpenID Connect scopes: **openid**, **email**, **phone**, **profile**

7. Click **Create user pool**

8. **Note down these values** (you'll need them for env vars):
   - User Pool ID (format: `us-east-1_XXXXXXXXX`) — found on the user pool overview page
   - App Client ID (format: 26-char alphanumeric) — found under App integration → App clients

---

## 2. Amazon SNS — SMS for Phone OTP

Cognito uses SNS to send SMS messages. By default, your AWS account is in the **SMS sandbox** which only allows sending to verified numbers.

### For Development (SMS Sandbox)

1. Open **AWS Console** → search **Amazon SNS** → **Text messaging (SMS)**
2. Go to **Sandbox destination phone numbers**
3. Click **Add phone number** → enter your test phone number → verify it with the code sent
4. Repeat for any other test numbers
5. That's it — Cognito will now be able to send OTPs to these verified numbers

### For Production (Exit Sandbox)

1. In SNS console → **Text messaging (SMS)** → click **Exit SMS sandbox**
2. Fill in the request:
   - **Use case description**: "Authentication OTPs for an education platform. Users verify phone numbers during signup and login."
   - **Expected monthly SMS volume**: estimate your volume
   - **Preferred countries**: list the countries your users are in (e.g., India)
3. AWS reviews within 1-2 business days
4. Once approved, set a **monthly SMS spend limit** (default is $1):
   - SNS → Text messaging → **Edit** → set spending limit (e.g., $100)

### SMS Pricing

- India: ~$0.02 per SMS
- US: ~$0.00645 per SMS
- Budget accordingly based on expected signups

---

## 3. Amazon SES — Email Delivery (Production)

For development, Cognito's built-in email works (50 emails/day). For production, switch to SES.

### When to Set This Up

- Skip for now if you're just building/testing locally
- Set up when you're ready for production or need more than 50 emails/day

### Steps

1. Open **AWS Console** → search **Amazon SES**

2. **Verify your domain**
   - Go to **Verified identities** → **Create identity**
   - Select **Domain** → enter your domain (e.g., `learnlikemagic.com`)
   - SES gives you DNS records (DKIM) to add
   - Add these records in your DNS provider (Route53, Cloudflare, etc.)
   - Wait for verification (usually minutes, can take up to 72 hours)

3. **Exit SES sandbox**
   - By default, SES only sends to verified emails
   - Go to **Account dashboard** → **Request production access**
   - Fill in:
     - Mail type: Transactional
     - Use case: "Sending email verification codes and password reset links for an education platform"
   - AWS reviews within 1-2 business days

4. **Connect SES to Cognito**
   - Go back to **Cognito** → your user pool → **Messaging** → **Edit**
   - Email provider: **Send email with Amazon SES**
   - FROM email address: `noreply@learnlikemagic.com` (must be on your verified domain)
   - SES Region: select the region where you verified your domain
   - Save

---

## 4. Google OAuth — "Continue with Google"

### Step 1: Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use an existing one): `LearnLikeMagic`
3. Go to **APIs & Services** → **OAuth consent screen**
   - User type: **External**
   - App name: `LearnLikeMagic`
   - User support email: your email
   - Authorized domains: add your domain (e.g., `learnlikemagic.com`)
   - Developer contact: your email
   - Click **Save and Continue**
   - Scopes: click **Add or Remove Scopes** → add `email`, `profile`, `openid` → Save
   - Test users: add your test email addresses (only needed while in "Testing" status)
   - Save

4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: `LearnLikeMagic Web`
   - Authorized JavaScript origins:
     - `http://localhost:3000` (dev)
     - `https://your-production-domain.com` (prod, add later)
   - Authorized redirect URIs:
     - `https://learnlikemagic.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` (your Cognito domain)
     - `http://localhost:3000/auth/callback` (for direct frontend Google sign-in)
   - Click **Create**

5. **Note down**:
   - Client ID (format: `xxxxxxxxxxxx.apps.googleusercontent.com`)
   - Client Secret

### Step 2: Add Google as Cognito Identity Provider

1. Go to **Cognito** → your user pool → **Sign-in experience** → **Federated identity provider sign-in**
2. Click **Add identity provider** → **Google**
3. Enter:
   - Client ID: from step 1
   - Client Secret: from step 1
   - Authorized scopes: `openid email profile`
4. Map attributes:
   - Google `email` → Cognito `email`
   - Google `name` → Cognito `name`
   - Google `sub` → Cognito `username`
5. Save

6. Go to **App integration** → your app client → **Edit hosted UI**
   - Under Identity providers, check **Google** alongside **Cognito user pool**
   - Save

### Publishing the OAuth App

- While in "Testing" status, only test users you added can sign in
- When ready for production: go to **OAuth consent screen** → click **Publish App**
- Google may require a review if you request sensitive scopes (email/profile are not sensitive, so usually instant)

---

## 5. Environment Variables

After completing the steps above, add these to your `.env` file (backend) and frontend config:

### Backend `.env`

```bash
# --- Auth (new) ---
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_REGION=us-east-1

# --- Existing (unchanged) ---
DATABASE_URL=postgresql://...
OPENAI_API_KEY=sk-...
# ... rest of existing vars
```

### Frontend `.env`

```bash
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
VITE_COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_REGION=us-east-1
VITE_GOOGLE_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
```

---

## 6. Database Migration

After the code is implemented, run the migration to create the `users` table and add `user_id` to `sessions`.

```bash
# Migration script will be provided with the implementation
# Typical command:
python -m alembic upgrade head
```

> Note: Alembic (or equivalent migration tool) will be added as part of the implementation. You don't need to set this up manually.

---

## 7. Checklist

### Dev Setup (completed 2026-02-19)

- [x] AWS Cognito user pool created — `us-east-1_bcCiF7myD`
- [x] App client created (no client secret) — `6jae1kj5sp5slr9sobi7phk60`
- [x] Cognito domain configured — `learnlikemagic.auth.us-east-1.amazoncognito.com`
- [x] SNS sandbox: test phone number added — `+919704983498`
- [x] Backend `.env` updated with Cognito values
- [x] Frontend `.env` updated with Cognito values
- [x] Database migration applied (`python db.py --migrate`)
- [x] IAM role created for Cognito SMS — `cognito-sns-role`
- [x] Email signup + verification flow tested end-to-end

### Google OAuth (completed 2026-02-19)

- [x] Google Cloud project created — `learnlikemagic`
- [x] Google OAuth credentials created — `888542865092-vn7id06u7gc89b2vvq82pe6h72v0qdsa.apps.googleusercontent.com`
- [x] Google added as Cognito identity provider
- [x] Frontend `.env` updated with `VITE_GOOGLE_CLIENT_ID`
- [x] Google OAuth app published

### Production Readiness

- [ ] **SNS sandbox exit** — Go to SNS Console → Text messaging → Exit SMS sandbox. Use case: "Authentication OTPs for an education platform." AWS reviews in 1-2 business days. After approval, set monthly SMS spend limit (default $1, raise to ~$100).
- [ ] **SES domain verified** — Verify `learnlikemagic.com` in SES, add DKIM DNS records.
- [ ] **SES sandbox exit** — Request production access in SES console. Mail type: Transactional. AWS reviews in 1-2 business days.
- [ ] **SES connected to Cognito** — Switch Cognito email provider from "Cognito default" to SES. Set FROM address to `noreply@learnlikemagic.com`.
- [ ] **Google OAuth app published** — Go to Google Cloud Console → OAuth consent screen → Publish App.
- [ ] **Production callback URLs** — Add production domain to Cognito app client callback/signout URLs and Google OAuth authorized redirect URIs.
