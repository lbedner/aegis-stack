# Services and Discovery

The `app/services` directory is the heart of your application's business logic. It's where you answer the question, "What does my application *do*?"

## The Service Layer Pattern

A "service" is a focused Python module that manages a specific piece of business logic or a connection to an external resource. This pattern separates the core logic of your application from the web-serving and UI-rendering logic, making the entire system easier to test, maintain, and reason about.

**Good candidates for a service include:**

- **Database Interactions:** A `database_service.py` that contains all your data access logic (CRUD operations).
- **External API Clients:** A `stripe_service.py` that handles all communication with the Stripe API.
- **Complex Business Logic:** A `reporting_service.py` that performs complex data transformations.
- **File Processing:** A `file_processing_service.py` for handling uploads.

The API layer in `app/backend/api/` should remain "thin." Its job is to handle HTTP requests and validation, then call the appropriate service to do the actual work.

## Automatic Service Discovery

Aegis Stack uses a dynamic discovery mechanism to make services "pluggable." You do not need to manually import your services into the main application for them to be active.

### How it Works

1.  At startup, the application scans the `app/services` directory.
2.  It automatically imports any Python module it finds within that directory.
3.  This import triggers the top-level code in the service file, which is where services can register themselves with other parts of the application, such as the [Lifecycle Registry](./lifecycle.md).

### The Developer Experience

This system creates a powerful and simple developer workflow:

1.  Create a new file in `app/services`.
2.  Write your service logic and any necessary lifecycle hooks.
3.  Run the application.

The service is automatically discovered and integrated into the application. There is no need to modify any central configuration or integration files.