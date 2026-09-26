# Examples

Real-world usage patterns for the Communications Service.

## Basic Usage

### Send Welcome Email

```python
from app.services.comms.email import send_email_simple

async def send_welcome_email(user_email: str, user_name: str) -> None:
    """Send welcome email to new user."""
    await send_email_simple(
        to=user_email,
        subject="Welcome to Our Platform!",
        html=f"""
        <h1>Welcome, {user_name}!</h1>
        <p>Thanks for signing up. Here's what you can do next:</p>
        <ul>
            <li>Complete your profile</li>
            <li>Explore our features</li>
            <li>Join our community</li>
        </ul>
        <p>If you have any questions, reply to this email.</p>
        """,
    )
```

### Send Verification Code

```python
from app.services.comms.sms import send_sms_simple

async def send_verification_code(phone: str, code: str) -> None:
    """Send SMS verification code."""
    await send_sms_simple(
        to=phone,
        body=f"Your verification code is: {code}\n\nThis code expires in 10 minutes.",
    )
```

### Password Reset Flow

```python
from app.services.comms.email import send_email_simple

async def send_password_reset(email: str, reset_token: str) -> None:
    """Send password reset email."""
    reset_url = f"https://yourapp.com/reset?token={reset_token}"

    await send_email_simple(
        to=email,
        subject="Reset Your Password",
        html=f"""
        <h1>Password Reset Request</h1>
        <p>Click the link below to reset your password:</p>
        <p><a href="{reset_url}">Reset Password</a></p>
        <p>This link expires in 1 hour.</p>
        <p>If you didn't request this, ignore this email.</p>
        """,
        text=f"Reset your password: {reset_url}",
    )
```

## Worker Integration with arq

Use the worker component to send emails and SMS asynchronously as background jobs.

### Why Use Workers?

- **Non-blocking** - Don't make users wait for email/SMS to send
- **Retry logic** - Automatic retries on failure
- **Rate limiting** - Control throughput to providers
- **Reliability** - Jobs persist in Redis queue

### Project Setup

Generate a project with both comms and worker components:

```bash
aegis init my-app --services comms --components worker
cd my-app
uv sync && source .venv/bin/activate
```

### Define Email Worker Task

Create a worker task for sending emails:

```python
# app/components/worker/tasks/comms.py
from arq import Retry
from app.services.comms.email import send_email
from app.services.comms.models import SendEmailRequest
from app.core.log import logger


async def send_email_task(
    ctx: dict,
    to: list[str],
    subject: str,
    text: str | None = None,
    html: str | None = None,
) -> dict:
    """
    Worker task to send email asynchronously.

    Args:
        ctx: arq context
        to: List of recipient emails
        subject: Email subject
        text: Plain text body
        html: HTML body

    Returns:
        Result with email ID and status
    """
    logger.info(f"Sending email to {to}")

    try:
        request = SendEmailRequest(
            to=to,
            subject=subject,
            text=text,
            html=html,
        )
        result = await send_email(request)

        logger.info(f"Email sent successfully: {result.id}")
        return {
            "status": "sent",
            "id": result.id,
            "to": result.to,
        }

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        # Retry up to 3 times with exponential backoff
        raise Retry(defer=ctx.get("job_try", 1) * 60)


async def send_sms_task(
    ctx: dict,
    to: str,
    body: str,
) -> dict:
    """
    Worker task to send SMS asynchronously.

    Args:
        ctx: arq context
        to: Recipient phone number
        body: Message text

    Returns:
        Result with message SID and status
    """
    from app.services.comms.sms import send_sms
    from app.services.comms.models import SendSMSRequest

    logger.info(f"Sending SMS to {to}")

    try:
        request = SendSMSRequest(to=to, body=body)
        result = await send_sms(request)

        logger.info(f"SMS sent successfully: {result.sid}")
        return {
            "status": "sent",
            "sid": result.sid,
            "to": result.to,
            "segments": result.segments,
        }

    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        raise Retry(defer=ctx.get("job_try", 1) * 60)
```

### Register Tasks with Worker

Add tasks to your worker configuration:

```python
# app/components/worker/main.py
from app.components.worker.tasks.comms import send_email_task, send_sms_task

# Add to your worker functions list
functions = [
    send_email_task,
    send_sms_task,
    # ... other tasks
]
```

### Queue Jobs from Your Application

```python
from app.components.worker.pools import get_queue_pool

async def queue_welcome_email(user_email: str, user_name: str) -> None:
    """Queue welcome email as background job."""
    pool, queue_name = await get_queue_pool()

    await pool.enqueue_job(
        "send_email_task",
        to=[user_email],
        subject="Welcome to Our Platform!",
        html=f"<h1>Welcome, {user_name}!</h1><p>Thanks for joining!</p>",
        _queue_name=queue_name,
    )


async def queue_verification_sms(phone: str, code: str) -> None:
    """Queue SMS verification as background job."""
    pool, queue_name = await get_queue_pool()

    await pool.enqueue_job(
        "send_sms_task",
        to=phone,
        body=f"Your code: {code}",
        _queue_name=queue_name,
    )
```

### Integration with Auth Service

Send welcome email when user registers:

```python
# app/components/backend/api/auth/router.py
from app.components.worker.pools import get_queue_pool

@router.post("/register")
async def register(user_data: UserCreate) -> User:
    """Register new user and send welcome email."""
    # Create user
    user = await user_service.create_user(user_data)

    # Queue welcome email as background job (non-blocking)
    pool, queue_name = await get_queue_pool()
    await pool.enqueue_job(
        "send_email_task",
        to=[user.email],
        subject="Welcome!",
        html=f"<h1>Welcome, {user.name}!</h1>",
        _queue_name=queue_name,
    )

    return user
```

The worker task uses the actual `send_email` function:

```python
# app/components/worker/tasks/comms.py
async def send_email_task(
    ctx: dict,
    to: list[str],
    subject: str,
    text: str | None = None,
    html: str | None = None,
) -> dict:
    """Worker task that calls the real send_email function."""
    request = SendEmailRequest(
        to=to,
        subject=subject,
        text=text,
        html=html,
    )

    # This calls the actual Resend API
    result = await send_email(request)

    return {
        "status": "sent",
        "id": result.id,
        "to": result.to,
    }
```

### Batch Email Sending

Send emails to multiple recipients efficiently:

```python
from app.components.worker.pools import get_queue_pool

async def send_newsletter(
    recipients: list[str],
    subject: str,
    content: str,
) -> None:
    """Queue newsletter for all recipients."""
    pool, queue_name = await get_queue_pool()

    for email in recipients:
        await pool.enqueue_job(
            "send_email_task",
            to=[email],
            subject=subject,
            html=content,
            _queue_name=queue_name,
        )

    print(f"Queued {len(recipients)} emails")
```

### Running the Worker

Start the worker to process queued jobs:

```bash
# Terminal 1: Run your application
make serve

# Terminal 2: Run the worker
arq app.components.worker.main.WorkerSettings
```

Or with Docker Compose:

```bash
docker compose up
# Worker runs automatically as a separate service
```

## Advanced Patterns

### Scheduled Communications

Use the scheduler component with comms:

```python
# app/services/digest/jobs.py
from app.services.comms.email import send_email_simple

async def send_daily_digest() -> None:
    """Send daily digest email to all users."""
    users = await get_subscribed_users()

    for user in users:
        await send_email_simple(
            to=user.email,
            subject="Your Daily Digest",
            html=generate_digest_html(user),
        )

# app/components/scheduler/jobs.py: daily at 8am
ServiceJob(
    send_daily_digest,
    "daily_digest",
    "Daily Digest Email",
    {"trigger": "cron", "hour": 8, "minute": 0},
)
```

### Multi-Channel Notifications

Send to multiple channels based on user preferences:

```python
from app.services.comms.email import send_email_simple
from app.services.comms.sms import send_sms_simple

async def notify_user(
    user: User,
    message: str,
    subject: str = "Notification",
) -> None:
    """Send notification via user's preferred channel."""

    if user.notify_email:
        await send_email_simple(
            to=user.email,
            subject=subject,
            text=message,
        )

    if user.notify_sms and user.phone:
        await send_sms_simple(
            to=user.phone,
            body=message,
        )
```

### Order Confirmation

Complete e-commerce order confirmation:

```python
async def send_order_confirmation(order: Order) -> None:
    """Send order confirmation email and SMS."""

    # Email with full details
    await send_email_simple(
        to=order.customer_email,
        subject=f"Order Confirmed: #{order.id}",
        html=f"""
        <h1>Order Confirmed!</h1>
        <p>Order #: {order.id}</p>
        <p>Total: ${order.total:.2f}</p>
        <h2>Items:</h2>
        <ul>
            {"".join(f"<li>{item.name} x {item.qty}</li>" for item in order.items)}
        </ul>
        <p>Expected delivery: {order.delivery_date}</p>
        """,
    )

    # SMS with summary
    if order.customer_phone:
        await send_sms_simple(
            to=order.customer_phone,
            body=f"Order #{order.id} confirmed! Total: ${order.total:.2f}. Delivery: {order.delivery_date}",
        )
```

### Two-Factor Authentication

Implement 2FA with SMS:

```python
import secrets
from datetime import datetime, timedelta

# Store codes temporarily (use Redis in production)
verification_codes: dict[str, tuple[str, datetime]] = {}

async def send_2fa_code(user_id: str, phone: str) -> None:
    """Generate and send 2FA code."""
    code = secrets.token_hex(3).upper()  # 6 char hex code
    expires = datetime.now() + timedelta(minutes=5)

    # Store code
    verification_codes[user_id] = (code, expires)

    # Send SMS
    await send_sms_simple(
        to=phone,
        body=f"Your verification code: {code}\nExpires in 5 minutes.",
    )

def verify_2fa_code(user_id: str, code: str) -> bool:
    """Verify 2FA code."""
    if user_id not in verification_codes:
        return False

    stored_code, expires = verification_codes[user_id]

    if datetime.now() > expires:
        del verification_codes[user_id]
        return False

    if code == stored_code:
        del verification_codes[user_id]
        return True

    return False
```

### Appointment Reminders

Schedule reminders before appointments:

```python
from datetime import timedelta
from app.components.worker.pools import get_queue_pool

async def schedule_appointment_reminder(
    appointment: Appointment,
    hours_before: int = 24,
) -> None:
    """Schedule SMS reminder before appointment."""
    reminder_time = appointment.datetime - timedelta(hours=hours_before)

    pool, queue_name = await get_queue_pool()
    await pool.enqueue_job(
        "send_sms_task",
        to=appointment.phone,
        body=f"Reminder: You have an appointment tomorrow at {appointment.time}. Reply CONFIRM to confirm or CANCEL to cancel.",
        _defer_until=reminder_time,
        _queue_name=queue_name,
    )
```

## Error Handling

### Graceful Degradation

```python
from app.services.comms.email import send_email_simple, EmailError

async def send_notification_with_fallback(
    email: str,
    phone: str,
    message: str,
) -> None:
    """Try email first, fall back to SMS on failure."""
    try:
        await send_email_simple(
            to=email,
            subject="Notification",
            text=message,
        )
    except EmailError as e:
        logger.warning(f"Email failed, trying SMS: {e}")
        await send_sms_simple(to=phone, body=message)
```

### Logging and Monitoring

```python
from app.core.log import logger

async def send_tracked_email(to: str, subject: str, body: str) -> str:
    """Send email with full logging."""
    logger.info(f"Sending email to {to}: {subject}")

    try:
        result = await send_email_simple(to=to, subject=subject, text=body)
        logger.info(f"Email sent successfully: {result.id}")
        return result.id
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        raise
```
