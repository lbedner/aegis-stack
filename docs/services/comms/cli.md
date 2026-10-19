# CLI Commands

Command-line interface reference for the Communications Service.

## Overview

The comms CLI provides commands for sending emails, SMS messages, and making voice calls directly from your terminal.

```bash
my-app comms --help
```

## Status Command

Check the configuration status of all communication channels.

```bash
my-app comms status
```

**Output**

```
Communications Service Status
==================================================

Email (Resend)
  Status: Configured
  API Key: Set
  From Email: noreply@example.com

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

## Email Commands

### Send Email

Send an email to one or more recipients.

```bash
my-app comms email send RECIPIENT [OPTIONS]
```

**Arguments**

| Argument | Description |
|----------|-------------|
| `RECIPIENT` | Email address of the recipient |

**Options**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--subject`, `-s` | `string` | Yes | Email subject line |
| `--text`, `-t` | `string` | No* | Plain text body |
| `--html` | `string` | No* | HTML body |
| `--from` | `string` | No | Override default sender |

*Either `--text` or `--html` is required.

**Examples**

```bash
# Send plain text email
my-app comms email send 'user@example.com' --subject 'Welcome' --text 'Hello, welcome to our service!'

# Send HTML email
my-app comms email send 'user@example.com' --subject 'Newsletter' --html '<h1>Weekly Update</h1><p>Here is what happened...</p>'

# Send with custom from address
my-app comms email send 'user@example.com' --subject 'Support' --text 'We received your request' --from 'support@yourdomain.com'

# Send both text and HTML (multipart)
my-app comms email send 'user@example.com' --subject 'Important' --text 'Plain text version' --html '<p>HTML version</p>'
```

**Output**

```
Sending email...

Email sent successfully!
   ID: email-123456
   To: user@example.com
   Status: sent
```

## SMS Commands

### Send SMS

Send an SMS message to a phone number.

```bash
my-app comms sms send TO BODY [OPTIONS]
```

**Arguments**

| Argument | Description |
|----------|-------------|
| `TO` | Recipient phone number (E.164 format: +15551234567) |
| `BODY` | Message text |

**Options**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--from` | `string` | No | Override default sender number |

**Examples**

```bash
# Send basic SMS
my-app comms sms send '+15559876543' 'Your verification code is 123456'

# Send with custom from number
my-app comms sms send '+15559876543' 'Hello from marketing' --from '+15557654321'

# Send longer message (will be segmented)
my-app comms sms send '+15559876543' 'This is a longer message that will be split into multiple segments because it exceeds the 160 character limit for a single SMS message segment.'
```

**Output**

```
Sending SMS...

SMS sent successfully!
   SID: SM1234567890abcdef
   To: +15559876543
   Status: sent
   Segments: 1
```

### Phone Number Format

Phone numbers must be in E.164 format:
- Start with `+`
- Include country code
- No spaces or dashes

| Format | Valid |
|--------|-------|
| `+15551234567` | Yes |
| `+44201234567` | Yes |
| `555-123-4567` | No |
| `(555) 123-4567` | No |

## Voice Call Commands

### Make Call

Initiate a voice call to a phone number.

```bash
my-app comms call make TO TWIML_URL [OPTIONS]
```

**Arguments**

| Argument | Description |
|----------|-------------|
| `TO` | Recipient phone number (E.164 format) |
| `TWIML_URL` | URL returning TwiML instructions for the call |

**Options**

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--from` | `string` | No | Override default caller ID |
| `--timeout` | `integer` | No | Ring timeout in seconds (default: 30) |

**Examples**

```bash
# Make call with demo TwiML
my-app comms call make '+15559876543' 'http://demo.twilio.com/docs/voice.xml'

# Make call with custom TwiML endpoint
my-app comms call make '+15559876543' 'https://yourapp.com/twiml/greeting'

# Make call with custom timeout
my-app comms call make '+15559876543' 'https://yourapp.com/twiml/greeting' --timeout 60
```

**Output**

```
Initiating call...

Call initiated successfully!
   SID: CA1234567890abcdef
   To: +15559876543
   Status: queued
```

### TwiML URLs

The TwiML URL must return valid TwiML XML that tells Twilio what to do:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Hello! This is a test call.</Say>
</Response>
```

**Demo TwiML URLs**

- `http://demo.twilio.com/docs/voice.xml` - Simple greeting
- `http://demo.twilio.com/welcome/voice/` - Welcome message

## Providers Command

Show information about configured providers.

```bash
my-app comms providers
```

**Output**

```
Communication Providers
==================================================

Email Provider: Resend
   Website: https://resend.com
   Docs: https://resend.com/docs

SMS Provider: Twilio
   Website: https://twilio.com
   Docs: https://twilio.com/docs/sms

Voice Provider: Twilio
   Website: https://twilio.com
   Docs: https://twilio.com/docs/voice
```

## Error Handling

### Configuration Errors

If a service is not configured, you'll see:

```
Error: Email not configured

Missing configuration:
  - RESEND_API_KEY is not set

Run 'my-app comms status' to see full configuration status.
```

### Provider Errors

If the provider returns an error:

```
Error: SMS provider error

Twilio error: The 'To' number +15559876543 is not a valid phone number.

Check:
  - Phone number format (must be E.164: +15551234567)
  - Trial accounts can only send to verified numbers
```

### Validation Errors

If required arguments are missing:

```
Error: Missing required option

Either --text or --html is required for email content.

Example:
  my-app comms email send 'user@example.com' --subject 'Hello' --text 'Your message here'
```

## Quick Reference

```bash
# Check status
my-app comms status

# Send email
my-app comms email send 'user@example.com' --subject 'Subject' --text 'Body'

# Send SMS
my-app comms sms send '+15551234567' 'Message body'

# Make call (uses demo TwiML by default)
my-app comms call make '+15551234567'

# Show providers
my-app comms providers

# Get help
my-app comms --help
my-app comms email --help
my-app comms sms --help
my-app comms call --help
```
