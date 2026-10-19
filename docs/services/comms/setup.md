# Provider Setup Guide

This guide walks you through setting up Resend and Twilio for the Communications Service.

## Resend (Email)

[Resend](https://resend.com) is a modern email API built for developers with excellent deliverability and simple integration.

### Sign Up

1. Go to [resend.com](https://resend.com)
2. Sign up for a free account
3. Verify your email address

### Free Tier

- **100 emails/day**
- **3,000 emails/month**
- No credit card required

### Get API Key

1. Go to [resend.com/api-keys](https://resend.com/api-keys)
2. Click "Create API Key"
3. Name it (e.g., "aegis-dev")
4. Copy the key (starts with `re_`)

!!! warning "Save Your Key"
    API keys are only shown once. Save it immediately to your `.env` file.

### Configure Domain (Production)

For production use, you need to verify a domain:

1. Go to [resend.com/domains](https://resend.com/domains)
2. Click "Add Domain"
3. Add the DNS records shown (SPF, DKIM, DMARC)
4. Wait for verification (usually a few minutes)

**For development** (no domain verification needed):
```bash
RESEND_FROM_EMAIL=onboarding@resend.dev
```

!!! tip "Use This for Testing"
    If you don't have your own verified domain, use `onboarding@resend.dev` - it works immediately with any Resend account.

### Environment Variables

```bash
# .env

# Required - Your Resend API key
RESEND_API_KEY=re_xxxxxxxxxxxx

# Required - Sender email address
# Use Resend's test address (works immediately, no domain verification)
RESEND_FROM_EMAIL=onboarding@resend.dev

# Or use your verified domain (requires DNS setup)
# RESEND_FROM_EMAIL=noreply@yourdomain.com
```

### Test Email Setup

```bash
# Check configuration
my-app comms status

# Send test email
my-app comms email send 'your@email.com' --subject 'Test from Aegis Stack' --text 'If you receive this, email is working!'
```

## Twilio (SMS & Voice)

[Twilio](https://twilio.com) is the industry standard for programmable SMS and voice communications.

### Sign Up

1. Go to [twilio.com/try-twilio](https://twilio.com/try-twilio)
2. Sign up for a free trial
3. Verify your phone number (required for trial)

### Free Trial

- **$15.50 USD trial credit**
- SMS: ~$0.0079/message (US)
- Voice: ~$0.0085/minute (US)
- Trial numbers show "Sent from Twilio trial" prefix

!!! info "Trial Limitations"
    Trial accounts can only send messages to **verified phone numbers**. Add your test numbers at [console.twilio.com/verified-caller-ids](https://console.twilio.com/us1/develop/phone-numbers/manage/verified).

### Get Credentials

1. Go to [console.twilio.com](https://console.twilio.com)
2. In the Account Info section, find:
   - **Account SID** (starts with `AC`)
   - **Auth Token** (click to reveal)

### Get a Toll-Free Number (Recommended)

!!! tip "Why Toll-Free?"
    Toll-free numbers have a simpler verification process than local numbers, which require A2P 10DLC registration. A2P 10DLC registration is **not available on trial accounts**.

1. Go to **Phone Numbers > Manage > Buy a Number**
2. Click **Toll-Free** tab
3. Select a number with SMS and Voice capabilities
4. Purchase with trial credit (~$2/month)

### Create Messaging Service

Required for toll-free SMS:

1. Go to **Messaging > Services**
2. Click **Create Messaging Service**
3. Name it (e.g., "Aegis Stack")
4. Select **Notify my users** as use case
5. Click **Add Senders** > **Phone Number**
6. Select your toll-free number
7. Complete setup wizard
8. Copy the **Messaging Service SID** (starts with `MG`)

### Complete Toll-Free Verification

After adding your toll-free number, you'll see a verification prompt:

1. Go to your number's properties
2. Click the verification link
3. Fill out business info (your name is fine for personal/dev use)
4. Describe your use case: "Development testing for application SMS notifications"
5. Submit and wait 1-2 business days for approval

!!! warning "Verification Required"
    You cannot send SMS until toll-free verification is approved.

### Environment Variables

```bash
# .env

# Required - Your Twilio credentials
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Your toll-free Twilio number (E.164 format)
TWILIO_PHONE_NUMBER=+18001234567

# Required for SMS - Your Messaging Service SID
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Verify Phone Numbers (Trial)

For trial accounts, you must verify recipient numbers:

1. Go to [console.twilio.com/verified-caller-ids](https://console.twilio.com/us1/develop/phone-numbers/manage/verified)
2. Click "Add a new Caller ID"
3. Enter the phone number to verify
4. Complete verification via call or SMS

### Test SMS Setup

```bash
# Check configuration
my-app comms status

# Send test SMS (to verified number, after toll-free verification approved)
my-app comms sms send '+1YOUR_VERIFIED_NUMBER' 'Test from Aegis Stack!'
```

### Test Voice Setup

Voice calls work immediately (no toll-free verification needed):

```bash
# Simple test (uses demo TwiML by default)
my-app comms call make '+1YOUR_VERIFIED_NUMBER'
```

### Create Custom Voice Messages (Optional)

To create your own voice messages, use TwiML Bins:

1. Go to **Develop > TwiML Bins** in Twilio Console
2. Click **Create new TwiML Bin**
3. Name it (e.g., "Appointment Reminder")
4. Add your TwiML:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello! This is a reminder about your appointment tomorrow.</Say>
</Response>
```
5. Save and copy the URL
6. Use it in your calls:
```bash
my-app comms call make '+1YOUR_NUMBER' 'https://handler.twilio.com/twiml/EHxxxxx'
```

## Verify Configuration

After setting up your environment variables, verify everything works:

```bash
# Check all services status
my-app comms status
```

Expected output:

```
Communications Service Status
==================================================

Email (Resend)
  Status: Configured
  API Key: Set
  From Email: onboarding@resend.dev

SMS (Twilio)
  Status: Configured
  Account SID: Set
  Auth Token: Set
  Phone Number: +15551234567

Voice (Twilio)
  Status: Configured
  Account SID: Set
  Auth Token: Set
  Phone Number: +15551234567

==================================================
3/3 services configured
```

## Complete Test

### Test Email

```bash
my-app comms email send 'your@email.com' --subject 'Test from Aegis Stack' --text 'This is a test email from the Communications Service!'
```

### Test SMS

```bash
# Note: Trial accounts can only send to verified numbers
my-app comms sms send '+1YOUR_VERIFIED_NUMBER' 'Test SMS from Aegis Stack!'
```

### Test Voice Call

```bash
# This will call your phone and play a demo message
my-app comms call make '+1YOUR_VERIFIED_NUMBER'
```

## Troubleshooting

### Email Issues

**Email not delivered**
- Check spam/junk folder
- Verify domain DNS records are correct (production)
- Ensure from address matches verified domain
- Check Resend dashboard for delivery status

**API key invalid**
- Ensure no extra spaces in environment variable
- Regenerate key if compromised
- Check key hasn't been revoked

### SMS Issues

**"Unverified number" error**
- Trial accounts can only send to verified numbers
- Add numbers at console.twilio.com/verified-caller-ids
- Upgrade to paid account for unrestricted sending

**A2P 10DLC / Error 30034**
- Local numbers require A2P 10DLC registration for SMS
- A2P 10DLC is not available on trial accounts
- Solution: Use a toll-free number instead

**Toll-free verification pending**
- Cannot send SMS until toll-free verification is approved
- Check status at your number's properties page
- Approval typically takes 1-2 business days

**Message not received**
- Check Twilio console for delivery status
- Verify phone number format (E.164: +15551234567)
- Check carrier filtering (some block shortcodes)
- Ensure Messaging Service SID is configured correctly

### Voice Issues

**Call not connecting**
- Verify TwiML URL is accessible
- Check Twilio console for call logs
- Ensure phone number has Voice capability

**No audio on call**
- TwiML must contain valid `<Say>` or `<Play>` verbs
- Check TwiML syntax at twilio.com/docs/voice/twiml

## Provider Documentation

- **Resend**: [resend.com/docs](https://resend.com/docs)
- **Twilio SMS**: [twilio.com/docs/sms](https://twilio.com/docs/sms)
- **Twilio Voice**: [twilio.com/docs/voice](https://twilio.com/docs/voice)

## Cost Estimates

### Resend Pricing

| Plan | Price | Emails/Month |
|------|-------|--------------|
| Free | $0 | 3,000 |
| Pro | $20/mo | 50,000 |
| Enterprise | Custom | Unlimited |

### Twilio Pricing (US)

| Service | Price |
|---------|-------|
| SMS Outbound | $0.0079/message |
| SMS Inbound | $0.0079/message |
| Voice Outbound | $0.0085/minute |
| Voice Inbound | $0.0085/minute |
| Phone Number | $1.15/month |

*Prices vary by country. Check provider websites for current rates.*
