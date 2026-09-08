# Communications Service

The Communications Service provides email, SMS, and voice call capabilities using industry-leading providers:

- **Email**: [Resend](https://resend.com) - Modern email API with excellent developer experience
- **SMS/Voice**: [Twilio](https://twilio.com) - Industry standard for programmable communications

## Quick Start

### 1. Install Dependencies

```bash
pip install resend twilio
# Or with project dependencies
pip install -e ".[comms]"
```

### 2. Configure Environment Variables

```bash
# Email (Resend)
export RESEND_API_KEY=re_xxxxxxxxxxxx
export RESEND_FROM_EMAIL=noreply@yourdomain.com

# SMS/Voice (Twilio)
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_PHONE_NUMBER=+15551234567
```

### 3. Check Configuration

```bash
{{ project_slug }} comms status
```

## Features

### Email
- Send emails with HTML or plain text content
- Support for CC, BCC, and reply-to
- Email tagging for analytics
- Webhook support for delivery tracking

### SMS
- Send SMS messages worldwide
- Automatic message segmentation
- Status callbacks
- Inbound SMS handling

### Voice
- Initiate outbound calls
- TwiML for call control
- Call status tracking
- Recording support

## Usage Examples

### CLI

```bash
# Send an email
{{ project_slug }} comms email send user@example.com \
  --subject "Welcome" \
  --text "Hello, welcome to our service!"

# Send an SMS
{{ project_slug }} comms sms send +15559876543 "Your verification code is 123456"

# Make a voice call
{{ project_slug }} comms call make +15559876543 "https://example.com/twiml/greeting.xml"

# Check service status
{{ project_slug }} comms status
```

### API

```python
import httpx

# Send email
response = httpx.post(
    "http://localhost:8000/api/v1/comms/email/send",
    json={
        "to": ["user@example.com"],
        "subject": "Welcome",
        "text": "Hello!",
    }
)
print(response.json())

# Send SMS
response = httpx.post(
    "http://localhost:8000/api/v1/comms/sms/send",
    json={
        "to": "+15559876543",
        "body": "Your code is 123456",
    }
)
print(response.json())
```

### Python

```python
from app.services.comms.email import send_email_simple
from app.services.comms.sms import send_sms_simple
from app.services.comms.calls import make_call_simple

# Send email
result = await send_email_simple(
    to="user@example.com",
    subject="Welcome",
    text="Hello, welcome!"
)
print(f"Email sent: {result.id}")

# Send SMS
result = await send_sms_simple(
    to="+15559876543",
    body="Your code is 123456"
)
print(f"SMS sent: {result.sid}")

# Make call
result = await make_call_simple(
    to="+15559876543",
    twiml_url="https://example.com/twiml"
)
print(f"Call initiated: {result.sid}")
```

## Provider Setup

- [Email Setup (Resend)](setup.md#resend-email)
- [SMS/Voice Setup (Twilio)](setup.md#twilio-sms-voice)

## API Reference

- [API Endpoints](api.md)
- [CLI Commands](cli.md)

## Next Steps

1. Set up your provider accounts (free tiers available)
2. Configure environment variables
3. Test with `comms status` command
4. Send your first message!
