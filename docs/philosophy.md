# Aegis Stack Philosophy

The core philosophy of Aegis Stack is built on three pillars: **Speed**, **Simplicity**, and **Scalability**.

## Speed: For Builders Who Refuse to Wait

Development should be fast. Aegis Stack is designed to get you from idea to production as quickly as possible.

- **Async-First:** Built from the ground up with `asyncio` to handle high-concurrency workloads efficiently.
- **Full-Stack Python:** Use a single language for your entire stack, from the Flet frontend to the FastAPI backend, reducing context-switching and cognitive load.
- **Minimalist by Default:** No unnecessary bloat. The stack provides a clean, strong foundation that you can build upon, not a heavy framework you have to fight against.

## Simplicity: Powerful Patterns, Not Prescriptive Frameworks

Aegis Stack favors clear, Pythonic patterns over complex, magical frameworks.

- **Composable Architecture:** Features like the lifecycle registry and service discovery are designed to be extended with plain Python, not complex plugin systems.
- **Clear Separation of Concerns:** The project structure is organized logically to separate the frontend, backend, core business logic (services), and framework plumbing.
- **Single Source of Truth:** Patterns like `mkdocstrings` are encouraged to keep documentation tied directly to the code, reducing drift and maintenance overhead.

## Scalability: From Monolith to Microservices

Aegis Stack is designed to grow with your application.

- **Monorepo Foundation:** Start with a simple, unified codebase that is easy to manage and develop.
- **Path to Distribution:** The architecture is structured to allow for a natural evolution into a distributed system. The same core `app` library can be used by different entrypoints to run the web server, background workers, and schedulers as independent, scalable services.