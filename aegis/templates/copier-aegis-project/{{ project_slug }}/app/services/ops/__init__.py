"""Operations adapters — CLI-driven provisioning of external services.

The first instance of an **OperationsAdapter pattern** for Aegis: a
protocol-shaped abstraction over external service vendors (registrars,
mail providers, eventually object storage / hosting / SSL) that lets a
single CLI command drive end-to-end production setup.

Today this hosts ``RegistrarAdapter`` (Porkbun) and ``MailProviderAdapter``
(Resend), composed by ``email_setup.setup_email_domain()`` and exposed
via the project's CLI. Same shape transfers cleanly to future ops (SSL
via Let's Encrypt, object storage via R2 / S3, etc.) — one protocol per
concern, vendor-specific adapter implementing it, thin orchestrator on
top.
"""

# Part of deploy: provisioning what a deployment needs (``ownership``).
PART_OF = "deploy"
