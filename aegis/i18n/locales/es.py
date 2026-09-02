"""Spanish locale — Definiciones de mensajes en español."""

MESSAGES: dict[str, str] = {
    # ── Validation ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "Nombre de proyecto inválido. Solo se permiten letras, números, "
        "guiones y guiones bajos."
    ),
    "validation.reserved_name": "'{name}' es un nombre reservado.",
    "validation.name_too_long": (
        "Nombre de proyecto demasiado largo. Máximo 50 caracteres."
    ),
    "validation.invalid_python": (
        "Versión de Python inválida '{version}'. Debe ser una de: {supported}"
    ),
    "validation.unknown_service": "Servicio desconocido: {name}",
    "validation.unknown_services": "Servicios desconocidos: {names}",
    "validation.unknown_component": "Componente desconocido: {name}",
    # ── Init command ───────────────────────────────────────────────────
    "init.title": "Inicialización de proyecto Aegis Stack",
    "init.location": "Ubicación:",
    "init.template_version": "Versión de plantilla:",
    "init.dir_exists": "El directorio '{path}' ya existe",
    "init.dir_exists_hint": "Usa --force para sobrescribir o elige otro nombre",
    "init.overwriting": "Sobrescribiendo directorio existente: {path}",
    "init.services_require": "Servicios requieren componentes: {components}",
    "init.compat_errors": "Errores de compatibilidad servicio-componente:",
    "init.suggestion_add": (
        "Sugerencia: Agrega componentes faltantes --components {components}"
    ),
    "init.suggestion_remove": (
        "O quita --components para que los servicios agreguen dependencias automáticamente."
    ),
    "init.suggestion_interactive": (
        "También puedes usar modo interactivo para agregar dependencias de servicios automáticamente."
    ),
    "init.auto_detected_scheduler": (
        "Auto-detectado: Scheduler con persistencia {backend}"
    ),
    "init.auto_added_deps": "Dependencias agregadas automáticamente: {deps}",
    "init.auto_added_by_services": "Agregado automáticamente por servicios:",
    "init.required_by": "requerido por {services}",
    "init.config_title": "Configuración del proyecto",
    "init.config_name": "Nombre:",
    "init.config_core": "Core:",
    "init.config_infra": "Infraestructura:",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "Servicios:",
    "init.component_files": "Archivos de componentes:",
    "init.entrypoints": "Puntos de entrada:",
    "init.worker_queues": "Colas de Worker:",
    "init.dependencies": "Dependencias a instalar:",
    "init.confirm_create": "¿Crear este proyecto?",
    "init.cancelled": "Creación de proyecto cancelada",
    "init.removing_dir": "Eliminando directorio existente: {path}",
    "init.creating": "Creando proyecto: {name}",
    "init.error": "Error al crear proyecto: {error}",
    "init.replay_hint": "Recrea esta configuración en cualquier momento:",
    # ── Interactive: section headers ───────────────────────────────────
    "interactive.component_selection": "Selección de componentes",
    "interactive.service_selection": "Selección de servicios",
    "interactive.core_included": (
        "Componentes core ({components}) incluidos automáticamente"
    ),
    "interactive.infra_header": "Componentes de infraestructura:",
    "interactive.services_intro": (
        "Los servicios proporcionan lógica de negocio para tu aplicación."
    ),
    # ── Component descriptions ──────────────────────────────────────────
    "component.backend": "Servidor backend FastAPI",
    "component.frontend": "Interfaz frontend Flet",
    "component.redis": "Redis cache y broker de mensajes",
    "component.worker": "Procesamiento de tareas en segundo plano (arq, Dramatiq o TaskIQ)",
    "component.scheduler": "Infraestructura de ejecución de tareas programadas",
    "component.database": "Base de datos con SQLModel ORM (SQLite o PostgreSQL)",
    "component.ingress": "Traefik reverse proxy y balanceador de carga",
    "component.observability": "Logfire observabilidad, trazas y métricas",
    "component.storage": "S3 object storage, SeaweedFS in dev",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Service descriptions ────────────────────────────────────────────
    "service.auth": "Autenticación y autorización de usuarios con tokens JWT",
    "service.ai": "Servicio de chatbot IA con soporte multi-framework",
    "service.comms": "Servicio de comunicaciones con email, SMS y voz",
    "service.documents": "Document store: keep the paper, deduped and findable",
    "service.blog": "Blog Markdown con borradores, publicación y etiquetas",
    # ── Interactive: component prompts ─────────────────────────────────
    "interactive.add_prompt": "¿Agregar {description}?",
    "interactive.add_with_redis": "¿Agregar {description}? (agregará Redis automáticamente)",
    "interactive.worker_configured": "Worker con backend {backend} configurado",
    # ── Interactive: scheduler ─────────────────────────────────────────
    "interactive.scheduler_persistence": "Persistencia de Scheduler:",
    "interactive.persist_prompt": (
        "¿Persistir tareas programadas? "
        "(Habilita historial de tareas, recuperación tras reinicios)"
    ),
    "interactive.scheduler_db_configured": "Scheduler + base de datos {engine} configurado",
    "interactive.bonus_backup": "Extra: Agregando tarea de respaldo de base de datos",
    "interactive.backup_desc": (
        "Tarea de respaldo diario de base de datos incluida (se ejecuta a las 2 AM)"
    ),
    # ── Interactive: database engine ───────────────────────────────────
    "interactive.db_engine_label": "Motor de base de datos {context}:",
    "interactive.db_select": "Selecciona motor de base de datos:",
    "interactive.db_sqlite": "SQLite - Simple, basado en archivo (ideal para desarrollo)",
    "interactive.db_postgres": (
        "PostgreSQL - Listo para producción, soporte multi-contenedor"
    ),
    "interactive.db_reuse": "Usando base de datos previamente seleccionada: {engine}",
    "interactive.db_provider_select": "Selecciona el host de PostgreSQL:",
    "interactive.db_provider_container": (
        "Contenedor local - postgres:16 en Docker (dev y prod)"
    ),
    "interactive.db_provider_neon": (
        "Neon - Postgres serverless (cloud en prod, contenedor local en dev)"
    ),
    # ── Interactive: worker backend ────────────────────────────────────
    "interactive.worker_label": "Backend de Worker:",
    "interactive.worker_select": "Selecciona backend de worker:",
    "interactive.worker_arq": "arq - Async, ligero (por defecto)",
    "interactive.worker_dramatiq": (
        "Dramatiq - Basado en procesos, ideal para trabajo CPU-bound"
    ),
    "interactive.worker_taskiq": (
        "TaskIQ - Async, estilo framework con brokers por cola"
    ),
    # ── Interactive: auth ──────────────────────────────────────────────
    "interactive.auth_header": "Servicios de autenticación:",
    "interactive.auth_level_label": "Nivel de autenticación:",
    "interactive.auth_select": "¿Qué tipo de autenticación?",
    "interactive.auth_basic": "Básico - Login con email/contraseña",
    "interactive.auth_rbac": "Con Roles - + control de acceso basado en roles (experimental)",
    "interactive.auth_org": "Con Organizaciones - + soporte multi-tenant (experimental)",
    "interactive.auth_selected": "Nivel de auth seleccionado: {level}",
    "interactive.auth_db_required": "Base de datos requerida:",
    "interactive.auth_db_reason": (
        "Autenticación requiere base de datos para almacenar usuarios"
    ),
    "interactive.auth_db_details": "(cuentas de usuario, sesiones, tokens JWT)",
    "interactive.auth_db_already": "Componente de base de datos ya seleccionado",
    "interactive.auth_db_confirm": "¿Continuar y agregar componente de base de datos?",
    "interactive.auth_cancelled": "Servicio de autenticación cancelado",
    "interactive.auth_db_configured": "Autenticación + Base de datos configurado",
    # ── Interactive: AI service ────────────────────────────────────────
    "interactive.ai_header": "Servicios de IA y Machine Learning:",
    "interactive.ai_framework_label": "Selección de framework IA:",
    "interactive.ai_framework_intro": "Elige tu framework de IA:",
    "interactive.ai_pydanticai": (
        "PydanticAI - Framework IA type-safe y Pythónico (recomendado)"
    ),
    "interactive.ai_langchain": (
        "LangChain - Framework popular con integraciones extensivas"
    ),
    "interactive.ai_use_pydanticai": "¿Usar PydanticAI? (recomendado)",
    "interactive.ai_selected_framework": "Framework seleccionado: {framework}",
    "interactive.ai_tracking_context": "Seguimiento de uso de IA",
    "interactive.ai_tracking_label": "Seguimiento de uso de LLM:",
    "interactive.ai_tracking_prompt": (
        "¿Habilitar seguimiento de uso? (conteo de tokens, costos, historial de conversaciones)"
    ),
    "interactive.ai_sync_label": "Sincronización de catálogo LLM:",
    "interactive.ai_sync_desc": (
        "Sincronizar obtiene datos actualizados de modelos desde APIs de OpenRouter/LiteLLM"
    ),
    "interactive.ai_sync_time": ("Requiere acceso a red y toma ~30-60 segundos"),
    "interactive.ai_sync_prompt": "¿Sincronizar catálogo LLM durante la generación del proyecto?",
    "interactive.ai_sync_will": "Catálogo LLM se sincronizará tras la generación del proyecto",
    "interactive.ai_sync_skipped": (
        "Sincronización LLM omitida - datos de fixture estáticos disponibles"
    ),
    "interactive.ai_provider_label": "Selección de proveedor IA:",
    "interactive.ai_provider_intro": (
        "Elige proveedores de IA a incluir (selección múltiple permitida)"
    ),
    "interactive.ai_provider_options": "Opciones de proveedor:",
    "interactive.ai_provider_recommended": "(Recomendado)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI - Modelos GPT (Pago)",
    "interactive.ai_provider.anthropic": "Anthropic - Modelos Claude (Pago)",
    "interactive.ai_provider.google": "Google - Modelos Gemini (Nivel gratuito)",
    "interactive.ai_provider.groq": "Groq - Inferencia rápida (Nivel gratuito)",
    "interactive.ai_provider.mistral": "Mistral - Modelos abiertos (Mayormente pago)",
    "interactive.ai_provider.cohere": "Cohere - Enfoque empresarial (Gratuito limitado)",
    "interactive.ai_provider.ollama": "Ollama - Inferencia local (Gratuito)",
    "interactive.ai_no_providers": (
        "Sin proveedores seleccionados, agregando valores predeterminados..."
    ),
    "interactive.ai_selected_providers": "Proveedores seleccionados: {providers}",
    "interactive.ai_deps_optimized": ("Dependencias optimizadas según tu selección"),
    "interactive.ai_ollama_label": "Modo de despliegue de Ollama:",
    "interactive.ai_ollama_intro": "¿Cómo quieres ejecutar Ollama?",
    "interactive.ai_ollama_host": (
        "Host - Conectar a Ollama en tu máquina (Mac/Windows)"
    ),
    "interactive.ai_ollama_docker": (
        "Docker - Ejecutar Ollama en contenedor Docker (Linux/Deploy)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "¿Conectar a Ollama del host? (recomendado para Mac/Windows)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama se conectará a host.docker.internal:11434"
    ),
    "interactive.ai_ollama_host_hint": "Asegúrate de que Ollama esté corriendo: ollama serve",
    "interactive.ai_ollama_docker_ok": (
        "Servicio Ollama se agregará a docker-compose.yml"
    ),
    "interactive.ai_ollama_docker_hint": (
        "Nota: El primer inicio puede tardar en descargar modelos"
    ),
    "interactive.ai_rag_label": "RAG (Retrieval-Augmented Generation):",
    "interactive.ai_rag_prompt": (
        "¿Habilitar RAG para indexación de documentos y búsqueda semántica?"
    ),
    "interactive.ai_rag_enabled": "RAG habilitado con almacén vectorial ChromaDB",
    "interactive.ai_voice_label": "Voz (Text-to-Speech y Speech-to-Text):",
    "interactive.ai_voice_prompt": (
        "¿Habilitar capacidades de voz? (TTS y STT para interacciones por voz)"
    ),
    "interactive.ai_voice_enabled": "Voz habilitada con soporte TTS y STT",
    "interactive.ai_db_already": "Base de datos ya seleccionada - seguimiento de uso habilitado",
    "interactive.ai_db_added": "Base de datos ({backend}) agregada para seguimiento de uso",
    "interactive.ai_configured": "Servicio de IA configurado",
    # ── Shared: validation ──────────────────────────────────────────────
    "shared.not_copier_project": "Proyecto en {path} no fue generado con Copier.",
    "shared.copier_only": (
        "El comando 'aegis {command}' solo funciona con proyectos generados por Copier."
    ),
    "shared.regenerate_hint": (
        "Para agregar componentes, regenera el proyecto con los nuevos componentes incluidos."
    ),
    "shared.git_not_initialized": "Proyecto no está en un repositorio git",
    "shared.git_required": "Actualizaciones de Copier requieren git para seguimiento de cambios",
    "shared.git_init_hint": (
        "Proyectos creados con 'aegis init' deberían tener git inicializado automáticamente"
    ),
    "shared.git_manual_init": (
        "Si creaste este proyecto manualmente, ejecuta: "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "Nombre de componente vacío no permitido",
    "shared.empty_service": "Nombre de servicio vacío no permitido",
    # ── Shared: next steps / review ──────────────────────────────────
    "shared.next_steps": "Próximos pasos:",
    "shared.next_make_check": "   1. Ejecuta 'make check' para verificar la actualización",
    "shared.next_test": "   2. Prueba tu aplicación",
    "shared.next_commit": "   3. Confirma los cambios con: git add . && git commit",
    "shared.review_header": "Revisa los cambios:",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "Operación cancelada",
    "shared.interactive_ignores_args": (
        "Advertencia: la opción --interactive ignora argumentos de componentes"
    ),
    "shared.no_components_selected": "Sin componentes seleccionados",
    "shared.no_services_selected": "Sin servicios seleccionados",
    # ── Add command ──────────────────────────────────────────────────
    "add.title": "Aegis Stack - Agregar componentes",
    "add.project": "Proyecto: {path}",
    "add.error_no_args": (
        "Error: argumento de componentes requerido (o usa --interactive)"
    ),
    "add.usage_hint": "Uso: aegis add scheduler,worker",
    "add.interactive_hint": "O: aegis add --interactive",
    "add.auto_added_deps": "Dependencias agregadas automáticamente: {deps}",
    "add.validation_failed": "Validación de componentes fallida: {error}",
    "add.load_config_failed": "No se pudo cargar configuración del proyecto: {error}",
    "add.already_enabled": "Ya habilitado: {components}",
    "add.all_enabled": "¡Todos los componentes solicitados ya están habilitados!",
    "add.components_to_add": "Componentes a agregar:",
    "add.scheduler_backend": "Backend de scheduler: {backend}",
    "add.confirm": "¿Agregar estos componentes?",
    "add.updating": "Actualizando proyecto...",
    "add.adding": "Agregando {component}...",
    "add.added_files": "{count} archivos agregados",
    "add.skipped_files": "{count} archivos existentes omitidos",
    "add.success": "¡Componentes agregados!",
    "add.failed_component": "Error al agregar {component}: {error}",
    "add.failed": "Error al agregar componentes: {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "Formato de componente inválido: {error}",
    "add.bracket_override": (
        "Sintaxis de corchetes 'scheduler[{engine}]' sobrescribe --backend {backend}"
    ),
    "add.invalid_scheduler_backend": "Backend de scheduler inválido: '{backend}'",
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "Opciones válidas: {options}",
    "add.postgres_coming": "Nota: Soporte para PostgreSQL disponible en versión futura",
    "add.auto_added_db": "Componente de base de datos agregado automáticamente para persistencia de scheduler",
    "add.generated_migration": "Migración generada: {name}",
    "add.scheduler_db_engine_mismatch": "No se puede usar el backend de scheduler '{backend}': el motor de base de datos del proyecto es '{engine}'. Deben coincidir.",
    # ── Remove command ────────────────────────────────────────────────
    "remove.title": "Aegis Stack - Eliminar componentes",
    "remove.project": "Proyecto: {path}",
    "remove.error_no_args": (
        "Error: argumento de componentes requerido (o usa --interactive)"
    ),
    "remove.usage_hint": "Uso: aegis remove scheduler,worker",
    "remove.interactive_hint": "O: aegis remove --interactive",
    "remove.no_selected": "Sin componentes seleccionados para eliminar",
    "remove.validation_failed": "Validación de componentes fallida: {error}",
    "remove.load_config_failed": "No se pudo cargar configuración del proyecto: {error}",
    "remove.cannot_remove_core": "No se puede eliminar componente core: {component}",
    "remove.not_enabled": "No habilitado: {components}",
    "remove.nothing_to_remove": "¡No hay componentes que eliminar!",
    "remove.auto_remove_redis": (
        "Eliminando redis automáticamente (sin funcionalidad independiente, solo usado por worker)"
    ),
    "remove.scheduler_persistence_warn": "IMPORTANTE: Advertencia de persistencia de Scheduler",
    "remove.scheduler_persistence_detail": (
        "Tu scheduler usa SQLite para persistencia de tareas."
    ),
    "remove.scheduler_db_remains": (
        "El archivo de base de datos en data/scheduler.db permanecerá."
    ),
    "remove.scheduler_keep_hint": (
        "Para conservar historial de tareas: Deja el componente de base de datos"
    ),
    "remove.scheduler_remove_hint": (
        "Para eliminar todos los datos: Elimina también el componente de base de datos"
    ),
    "remove.components_to_remove": "Componentes a eliminar:",
    "remove.warning_delete": (
        "ADVERTENCIA: ¡Esto ELIMINARÁ archivos de componentes de tu proyecto!"
    ),
    "remove.commit_hint": "Asegúrate de haber confirmado tus cambios en git.",
    "remove.confirm": "¿Eliminar estos componentes?",
    "remove.removing_all": "Eliminando componentes...",
    "remove.removing": "Eliminando {component}...",
    "remove.removed_files": "{count} archivos eliminados",
    "remove.failed_component": "Error al eliminar {component}: {error}",
    "remove.success": "¡Componentes eliminados!",
    "remove.failed": "Error al eliminar componentes: {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Manual updater ─────────────────────────────────────────────────
    "updater.processing_files": "Procesando {count} archivos de componentes...",
    "updater.updating_shared": "Actualizando archivos de plantilla compartidos...",
    "updater.shared_preserved": "Cambios locales conservados (regeneración omitida, combina manualmente): {file}",
    "updater.shared_merged": "Cambios de plantilla combinados en tu archivo personalizado: {file}",
    "updater.shared_conflict": "Conflicto de combinación (marcadores escritos, resuelve manualmente): {file}",
    "updater.running_postgen": "Ejecutando tareas post-generación...",
    "updater.deps_synced": "Dependencias sincronizadas (uv sync)",
    "updater.code_formatted": "Código formateado (make fix)",
    # ── Project map ──────────────────────────────────────────────────
    "projectmap.new": "NUEVO",
    # ── Post-generation: setup tasks ──────────────────────────────────
    "postgen.setup_start": "Configurando entorno de proyecto...",
    "postgen.deps_installing": "Instalando dependencias con uv...",
    "postgen.deps_success": "Dependencias instaladas",
    "postgen.deps_failed": "Generación de proyecto fallida: instalación de dependencias falló",
    "postgen.deps_failed_detail": (
        "Los archivos del proyecto generado permanecen, pero el proyecto no es utilizable."
    ),
    "postgen.deps_failed_hint": (
        "Corrige el problema de dependencias (verifica compatibilidad de versión de Python) e intenta de nuevo."
    ),
    "postgen.deps_warn_failed": "Advertencia: Instalación de dependencias falló",
    "postgen.deps_manual": "Ejecuta 'uv sync' manualmente tras crear el proyecto",
    "postgen.deps_timeout": (
        "Advertencia: Tiempo de espera en instalación de dependencias - ejecuta 'uv sync' manualmente"
    ),
    "postgen.deps_uv_missing": "Advertencia: uv no encontrado en PATH",
    "postgen.deps_uv_install": "Instala uv primero: https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "Advertencia: Instalación de dependencias falló: {error}",
    "postgen.env_setup": "Configurando entorno...",
    "postgen.env_created": "Archivo de entorno creado desde .env.example",
    "postgen.env_exists": "Archivo de entorno ya existe",
    "postgen.env_missing": "Advertencia: Archivo .env.example no encontrado",
    "postgen.env_error": "Advertencia: Configuración de entorno falló: {error}",
    "postgen.env_manual": "Copia .env.example a .env manualmente",
    # ── Post-generation: database/migrations ────────────────────────────
    "postgen.db_setup": "Configurando esquema de base de datos...",
    "postgen.db_success": "Tablas de base de datos creadas",
    "postgen.db_alembic_missing": "Advertencia: Archivo de configuración de Alembic no encontrado en {path}",
    "postgen.db_alembic_hint": (
        "Omitiendo migración de base de datos. Asegúrate de que el archivo de configuración exista "
        "y ejecuta 'alembic upgrade head' manualmente."
    ),
    "postgen.db_failed": "Advertencia: Configuración de migración de base de datos falló",
    "postgen.db_manual": "Ejecuta 'alembic upgrade head' manualmente tras crear el proyecto",
    "postgen.db_timeout": (
        "Advertencia: Tiempo de espera en migración - ejecuta 'alembic upgrade head' manualmente"
    ),
    "postgen.db_error": "Advertencia: Configuración de migración falló: {error}",
    # ── Post-generation: LLM fixtures/sync ────────────────────────────
    "postgen.llm_seeding": "Cargando fixtures de LLM...",
    "postgen.llm_seed_success": "Fixtures de LLM cargados",
    "postgen.llm_seed_failed": "Advertencia: Carga de fixtures de LLM falló",
    "postgen.llm_seed_manual": (
        "Puedes cargar fixtures manualmente ejecutando el cargador de fixtures"
    ),
    "postgen.llm_seed_timeout": "Advertencia: Tiempo de espera en carga de fixtures de LLM",
    "postgen.llm_seed_error": "Advertencia: Carga de fixtures de LLM falló: {error}",
    "postgen.llm_syncing": "Sincronizando catálogo LLM desde APIs externas...",
    "postgen.llm_sync_success": "Catálogo LLM sincronizado",
    "postgen.llm_sync_failed": "Advertencia: Sincronización de catálogo LLM falló",
    "postgen.llm_sync_manual": (
        "Ejecuta '{slug} llm sync' manualmente para poblar el catálogo"
    ),
    "postgen.llm_sync_timeout": "Advertencia: Tiempo de espera en sincronización de catálogo LLM",
    "postgen.llm_sync_error": "Advertencia: Sincronización de catálogo LLM falló: {error}",
    # ── Post-generation: formatting ───────────────────────────────────
    "postgen.format_timeout": (
        "Advertencia: Tiempo de espera en formateo - ejecuta 'make fix' manualmente"
    ),
    "postgen.format_error": "Advertencia: Auto-formateo omitido: {error}",
    "postgen.format_error_manual": "Ejecuta 'make fix' manualmente para formatear código",
    "postgen.format_start": "Auto-formateando código generado...",
    "postgen.format_success": "Formateo de código completado",
    "postgen.format_partial": (
        "Algunos problemas de formateo detectados, pero proyecto creado"
    ),
    "postgen.format_manual": "Ejecuta 'make fix' manualmente para resolver problemas restantes",
    "postgen.format_hint": "Ejecuta 'make fix' para formatear código",
    "postgen.llm_sync_skipped": "Sincronización de catálogo LLM omitida",
    "postgen.llm_fixtures_outdated": "Datos de fixture estáticos cargados (pueden estar desactualizados)",
    "postgen.llm_sync_hint": "Ejecuta '{slug} llm sync' después para obtener datos actualizados",
    "postgen.llm_fixtures_fallback": (
        "Datos de fixture estáticos disponibles pero pueden estar desactualizados"
    ),
    "postgen.ready": "¡Proyecto listo para ejecutar!",
    "postgen.next_steps": "Próximos pasos:",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Abrir Overseer: http://localhost:8000/dashboard/",
    # ── Post-generation: project map ──────────────────────────────────
    "projectmap.title": "Estructura del proyecto:",
    "projectmap.components": "Componentes",
    "projectmap.services": "Lógica de negocio",
    "projectmap.models": "Modelos de base de datos",
    "projectmap.cli": "Comandos CLI",
    "projectmap.entrypoints": "Puntos de ejecución",
    "projectmap.tests": "Suite de pruebas",
    "projectmap.migrations": "Migraciones",
    "projectmap.auth": "Autenticación",
    "projectmap.ai": "Conversaciones IA",
    "projectmap.comms": "Comunicaciones",
    "projectmap.insights": "Adoption metrics",
    "projectmap.payment": "Payments and subscriptions",
    "projectmap.documents": "Document store",
    "projectmap.blog": "Markdown blog",
    "projectmap.finance": "Personal finance",
    "projectmap.docs": "Documentación",
    # ── Post-generation: footer ───────────────────────────────────────
    "postgen.docs_link": "Docs: https://docs.aegis-stack.io",
    "postgen.star_prompt": (
        "Si Aegis Stack te facilitó la vida, considera dejar una estrella:"
    ),
    # ── Add-service command ────────────────────────────────────────────
    "add_service.title": "Aegis Stack - Agregar servicios",
    "add_service.project": "Proyecto: {path}",
    "add_service.error_no_args": (
        "Error: argumento de servicios requerido (o usa --interactive)"
    ),
    "add_service.usage_hint": "Uso: aegis add-service auth,ai",
    "add_service.interactive_hint": "O: aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "Advertencia: la opción --interactive ignora argumentos de servicios"
    ),
    "add_service.no_selected": "Sin servicios seleccionados",
    "add_service.already_enabled": "Ya habilitado: {services}",
    "add_service.all_enabled": "¡Todos los servicios solicitados ya están habilitados!",
    "add_service.validation_failed": "Validación de servicios fallida: {error}",
    "add_service.load_config_failed": "No se pudo cargar configuración del proyecto: {error}",
    "add_service.services_to_add": "Servicios a agregar:",
    "add_service.required_components": "Componentes requeridos (se agregarán automáticamente):",
    "add_service.already_have_components": (
        "Ya tiene componentes requeridos: {components}"
    ),
    "add_service.confirm": "¿Agregar estos servicios?",
    "add_service.adding_component": "Agregando componente requerido: {component}...",
    "add_service.failed_component": "Error al agregar componente {component}: {error}",
    "add_service.added_files": "{count} archivos agregados",
    "add_service.skipped_files": "{count} archivos existentes omitidos",
    "add_service.preserved_files": "{count} archivo(s) compartido(s) requieren revisión manual (ver mensajes arriba)",
    "add_service.adding_service": "Agregando servicio: {service}...",
    "add_service.failed_service": "Error al agregar servicio {service}: {error}",
    "add_service.resolve_failed": "Error al resolver dependencias de servicio: {error}",
    "add_service.bootstrap_alembic": "Inicializando infraestructura alembic...",
    "add_service.created_file": "Creado: {file}",
    "add_service.generated_migration": "Migración generada: {name}",
    "add_service.applying_migrations": "Aplicando migraciones de base de datos...",
    "add_service.migration_failed": (
        "Advertencia: Migración automática falló. Ejecuta 'make migrate' manualmente."
    ),
    "add_service.success": "¡Servicios agregados!",
    "add_service.failed": "Error al agregar servicios: {error}",
    "add_service.auth_setup": "Configuración de Auth:",
    "add_service.auth_create_users": "   1. Crear usuarios de prueba: {cmd}",
    "add_service.auth_view_routes": "   2. Ver rutas de auth: {url}",
    "add_service.ai_setup": "Configuración de IA:",
    "add_service.ai_set_provider": (
        "   1. Configura {env_var} en .env (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": "   2. Configura la API key del proveedor ({env_var}, etc.)",
    "add_service.ai_test_cli": "   3. Prueba con CLI: {cmd}",
    # ── Remove-service command ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack - Eliminar servicios",
    "remove_service.project": "Proyecto: {path}",
    "remove_service.error_no_args": (
        "Error: argumento de servicios requerido (o usa --interactive)"
    ),
    "remove_service.usage_hint": "Uso: aegis remove-service auth,ai",
    "remove_service.interactive_hint": "O: aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "Advertencia: la opción --interactive ignora argumentos de servicios"
    ),
    "remove_service.no_selected": "Sin servicios seleccionados para eliminar",
    "remove_service.not_enabled": "No habilitado: {services}",
    "remove_service.nothing_to_remove": "¡No hay servicios que eliminar!",
    "remove_service.validation_failed": "Validación de servicios fallida: {error}",
    "remove_service.load_config_failed": (
        "No se pudo cargar configuración del proyecto: {error}"
    ),
    "remove_service.services_to_remove": "Servicios a eliminar:",
    "remove_service.auth_warning": "IMPORTANTE: Advertencia de servicio Auth",
    "remove_service.auth_delete_intro": "Eliminar servicio auth borrará:",
    "remove_service.auth_delete_endpoints": "Endpoints API de autenticación de usuarios",
    "remove_service.auth_delete_models": "Modelo de usuario y servicios de autenticación",
    "remove_service.auth_delete_jwt": "Código de manejo de tokens JWT",
    "remove_service.auth_db_note": (
        "Nota: Tablas de base de datos y migraciones alembic NO se eliminan."
    ),
    "remove_service.warning_delete": (
        "ADVERTENCIA: ¡Esto ELIMINARÁ archivos de servicios de tu proyecto!"
    ),
    "remove_service.confirm": "¿Eliminar estos servicios?",
    "remove_service.removing": "Eliminando servicio: {service}...",
    "remove_service.failed_service": "Error al eliminar servicio {service}: {error}",
    "remove_service.removed_files": "{count} archivos eliminados",
    "remove_service.success": "¡Servicios eliminados!",
    "remove_service.failed": "Error al eliminar servicios: {error}",
    "remove_service.deps_not_removed": (
        "Nota: Dependencias de servicios (base de datos, etc.) NO fueron eliminadas."
    ),
    "remove_service.deps_remove_hint": (
        "Usa 'aegis remove <componente>' para eliminar componentes por separado."
    ),
    # ── Version command ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Components command ─────────────────────────────────────────────
    "components.core_title": "COMPONENTES CORE",
    "components.backend_desc": (
        "  backend      - Servidor backend FastAPI (siempre incluido)"
    ),
    "components.frontend_desc": (
        "  frontend     - Interfaz frontend Flet (siempre incluido)"
    ),
    "components.infra_title": "COMPONENTES DE INFRAESTRUCTURA",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "Requiere: {deps}",
    "components.recommends": "Recomienda: {deps}",
    "components.usage_hint": (
        "Usa 'aegis init NOMBRE_PROYECTO --components redis,worker' para seleccionar componentes"
    ),
    # ── Services command ───────────────────────────────────────────────
    "services.title": "SERVICIOS DISPONIBLES",
    "services.type_auth": "Servicios de autenticación",
    "services.type_payment": "Servicios de pago",
    "services.type_ai": "Servicios de IA y Machine Learning",
    "services.type_notification": "Servicios de notificaciones",
    "services.type_analytics": "Servicios de analítica",
    "services.type_storage": "Servicios de almacenamiento",
    "services.type_content": "Servicios de contenido",
    "services.type_finance": "Servicios de finanzas",
    "services.requires_components": "Requiere componentes: {deps}",
    "services.recommends_components": "Recomienda componentes: {deps}",
    "services.requires_services": "Requiere servicios: {deps}",
    "services.none_available": "  Sin servicios disponibles aún.",
    "services.usage_hint": (
        "Usa 'aegis init NOMBRE_PROYECTO --services auth' para agregar servicios"
    ),
    # ── Update command ─────────────────────────────────────────────────
    "update.title": "Aegis Stack - Actualizar plantilla",
    "update.not_copier": "Proyecto en {path} no fue generado con Copier.",
    "update.copier_only": (
        "El comando 'aegis update' solo funciona con proyectos generados por Copier."
    ),
    "update.need_regen": "Proyectos generados antes de v0.2.0 necesitan ser regenerados.",
    "update.project": "Proyecto: {path}",
    "update.commit_or_stash": (
        "Confirma o guarda tus cambios antes de ejecutar 'aegis update'."
    ),
    "update.clean_required": (
        "Copier requiere un árbol git limpio para fusionar cambios de forma segura."
    ),
    "update.git_clean": "Árbol git limpio",
    "update.dirty_tree": "Árbol git tiene cambios sin confirmar",
    "update.changelog_breaking": "Cambios incompatibles:",
    "update.changelog_features": "Nuevas funcionalidades:",
    "update.changelog_fixes": "Correcciones:",
    "update.changelog_other": "Otros cambios:",
    "update.current_commit": "   Actual: {commit}...",
    "update.target_commit": "   Destino: {commit}...",
    "update.unknown_version": "Advertencia: No se puede determinar versión actual de plantilla",
    "update.untagged_commit": (
        "Proyecto puede haber sido generado desde un commit sin etiqueta"
    ),
    "update.custom_template": "Usando plantilla personalizada ({source}): {path}",
    "update.version_info": "Información de versión:",
    "update.current_cli": "   CLI actual:        {version}",
    "update.current_template": "   Plantilla actual:  {version}",
    "update.current_template_commit": "   Plantilla actual:  {commit}... (commit)",
    "update.current_template_unknown": "   Plantilla actual:  desconocida",
    "update.target_template": "   Plantilla destino: {version}",
    "update.already_at_version": "Proyecto ya está en la versión solicitada",
    "update.already_at_commit": "Proyecto ya está en el commit destino",
    "update.ahead_of_target": (
        "El proyecto es más reciente que la versión de plantilla de destino"
    ),
    "update.ahead_of_target_hint": (
        "Nada que actualizar. Usa --to-version para elegir una versión concreta."
    ),
    "update.downgrade_blocked": "Degradación no soportada",
    "update.downgrade_reason": (
        "Copier no soporta degradación a versiones anteriores de plantilla."
    ),
    "update.changelog": "Registro de cambios:",
    "update.dry_run": "MODO DE PRUEBA - No se aplicarán cambios",
    "update.dry_run_hint": "Para aplicar esta actualización, ejecuta:",
    "update.confirm": "¿Aplicar esta actualización?",
    "update.cancelled": "Actualización cancelada",
    "update.creating_backup": "Creando punto de respaldo...",
    "update.backup_created": "   Respaldo creado: {tag}",
    "update.backup_failed": "No se pudo crear punto de respaldo",
    "update.updating": "Actualizando proyecto...",
    "update.updating_to": "Actualizando a versión de plantilla {version}",
    "update.moved_files": "   {count} archivos nuevos movidos desde directorio anidado",
    "update.synced_files": "   {count} cambios de plantilla sincronizados",
    "update.merge_conflicts": (
        "   {count} archivo(s) tienen conflictos de fusión (busca <<<<<<< para resolver):"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "Ejecutando tareas post-generación...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": "   __aegis_version__ actualizado a {version}",
    "update.success": "¡Actualización completada!",
    "update.partial_success": (
        "Actualización completada con algunos fallos en tareas post-generación"
    ),
    "update.partial_detail": "   Algunas tareas de configuración fallaron. Ver detalles arriba.",
    "update.next_steps": "Próximos pasos:",
    "update.next_review": "   1. Revisa cambios: git diff",
    "update.next_conflicts": "   2. Verifica conflictos (archivos *.rej)",
    "update.next_test": "   3. Ejecuta pruebas: make check",
    "update.next_commit": "   4. Confirma cambios: git add . && git commit",
    "update.failed": "Actualización falló: {error}",
    "update.rollback_prompt": "¿Revertir al estado anterior?",
    "update.manual_rollback": "Reversión manual: git reset --hard {tag}",
    "update.troubleshooting": "Solución de problemas:",
    "update.troubleshoot_clean": "   - Asegúrate de tener un árbol git limpio",
    "update.troubleshoot_version": "   - Verifica que la versión/commit exista",
    "update.troubleshoot_docs": "   - Revisa documentación de Copier para problemas de actualización",
    # ── Ingress command ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack - Habilitar Ingress TLS",
    "ingress.project": "Proyecto: {path}",
    "ingress.not_found": "Componente ingress no encontrado. Agregándolo primero...",
    "ingress.add_confirm": "¿Agregar componente ingress?",
    "ingress.add_failed": "Error al agregar componente ingress: {error}",
    "ingress.added": "Componente ingress agregado.",
    "ingress.tls_already": "TLS ya está habilitado en este proyecto.",
    "ingress.domain_label": "   Dominio: {domain}",
    "ingress.acme_email": "   Email ACME: {email}",
    "ingress.domain_prompt": (
        "Nombre de dominio (ej: example.com, o vacío para enrutamiento por IP)"
    ),
    "ingress.email_reuse": "Usando email existente para ACME: {email}",
    "ingress.email_prompt": "Email para notificaciones de Let's Encrypt",
    "ingress.email_required": (
        "Error: --email requerido para TLS (necesario para Let's Encrypt)"
    ),
    "ingress.tls_config": "Configuración TLS:",
    "ingress.domain_none": "   Dominio: (ninguno - enrutamiento por IP/PathPrefix)",
    "ingress.tls_confirm": "¿Habilitar TLS con esta configuración?",
    "ingress.enabling": "Habilitando TLS...",
    "ingress.updated_file": "   Actualizado: {file}",
    "ingress.created_file": "   Creado: {file}",
    "ingress.success": "¡TLS habilitado!",
    "ingress.available_at": "   Tu app estará disponible en: https://{domain}",
    "ingress.https_configured": "   HTTPS configurado con Let's Encrypt",
    "ingress.next_steps": "Próximos pasos:",
    "ingress.next_deploy": "   1. Despliega con: aegis deploy",
    "ingress.next_ports": "   2. Asegúrate de que los puertos 80 y 443 estén abiertos en tu servidor",
    "ingress.next_dns": (
        "   3. Apunta el registro DNS A de {domain} a la IP de tu servidor"
    ),
    "ingress.next_certs": "   Certificados se aprovisionarán automáticamente en la primera solicitud",
    # ── Deploy commands ────────────────────────────────────────────────
    "deploy.no_config": (
        "Sin configuración de despliegue. Ejecuta 'aegis deploy-init' primero."
    ),
    "deploy.init_saved": "Configuración de despliegue guardada en {file}",
    "deploy.init_host": "   Host: {host}",
    "deploy.init_user": "   Usuario: {user}",
    "deploy.init_path": "   Ruta: {path}",
    "deploy.init_docker_context": "   Docker Context: {context}",
    "deploy.prompt_host": "IP o hostname del servidor",
    "deploy.init_gitignore": (
        "Nota: Considera agregar .aegis/ a .gitignore para evitar confirmar config de despliegue"
    ),
    "deploy.setup_title": "Configurando servidor en {target}...",
    "deploy.checking_ssh": "Verificando conectividad SSH...",
    "deploy.adding_host_key": "Agregando servidor a known_hosts...",
    "deploy.ssh_keyscan_failed": "Error al escanear clave SSH del host: {error}",
    "deploy.ssh_failed": "Conexión SSH falló: {error}",
    "deploy.copying_script": "Copiando script de configuración al servidor...",
    "deploy.copy_failed": "Error al copiar script de configuración",
    "deploy.running_setup": "Ejecutando configuración del servidor (puede tardar unos minutos)...",
    "deploy.setup_failed": "Configuración del servidor falló",
    "deploy.setup_script_missing": "Script de configuración del servidor no encontrado: {path}",
    "deploy.setup_script_hint": (
        "Asegúrate de que tu proyecto fue creado con el componente ingress."
    ),
    "deploy.setup_complete": "¡Configuración del servidor completada!",
    "deploy.setup_verify": "Verificando instalación:",
    "deploy.setup_verify_docker": "  Docker: {version}",
    "deploy.setup_verify_compose": "  Docker Compose: {version}",
    "deploy.setup_verify_uv": "  uv: {version}",
    "deploy.setup_verify_app_dir": "  Directorio de app: {path}",
    "deploy.setup_next": "Siguiente: Ejecuta 'aegis deploy' para desplegar tu aplicación",
    # ── deploy-setup --public-key ──
    "deploy.pubkey_missing": "Public key file not found: {path}",
    "deploy.installing_pubkey": (
        "Installing public key into {user}'s authorized_keys..."
    ),
    "deploy.pubkey_install_failed": "Failed to install public key: {error}",
    "deploy.pubkey_installed": "  Public key installed",
    # ── deploy-cd-setup ──
    "deploy.cd_gh_not_installed": (
        "GitHub CLI (gh) is not installed. Install it from https://cli.github.com/"
    ),
    "deploy.cd_gh_not_authed": (
        "GitHub CLI is not authenticated. Run 'gh auth login' first."
    ),
    "deploy.cd_repo_not_detected": (
        "Could not detect GitHub repo from 'git remote get-url origin'. "
        "Pass --repo OWNER/NAME explicitly."
    ),
    "deploy.cd_already_configured": (
        "CD is already configured for this project (key fingerprint: "
        "{fingerprint}). Use --force to rotate."
    ),
    "deploy.cd_secret_exists": (
        "GitHub Actions secrets already exist: {names}. Use --force to overwrite."
    ),
    "deploy.cd_workflow_exists": (
        "Workflow already exists at {path}. Use --force to overwrite."
    ),
    "deploy.cd_title": ("Setting up GitHub Actions CD for {repo} → {target}..."),
    "deploy.cd_plan_header": "Plan:",
    "deploy.cd_plan_keygen": (
        "  1. Generate dedicated ed25519 deploy key (no passphrase)"
    ),
    "deploy.cd_plan_install": (
        "  2. Install public key in {user}@{host}:~/.ssh/authorized_keys"
    ),
    "deploy.cd_plan_secrets": (
        "  3. Push DEPLOY_SSH_KEY / DEPLOY_HOST / DEPLOY_USER to {repo} secrets"
    ),
    "deploy.cd_plan_workflow": "  4. Scaffold {path}",
    "deploy.cd_dry_run": "Dry run; no changes made.",
    "deploy.cd_generating_key": "Generating ed25519 deploy key...",
    "deploy.cd_keygen_failed": "ssh-keygen failed: {error}",
    "deploy.cd_installing_pubkey": ("Installing public key on {user}@{host}..."),
    "deploy.cd_install_failed": "Failed to install public key: {error}",
    "deploy.cd_pushing_secrets": "Pushing secrets to {repo}...",
    "deploy.cd_secret_failed": "Failed to set secret {name}: {error}",
    "deploy.cd_writing_workflow": "Writing {path}...",
    "deploy.cd_kept_key": "  Private key copy saved to {path}",
    "deploy.cd_complete": "GitHub Actions CD configured!",
    "deploy.cd_fingerprint": "  Deploy key fingerprint: {fingerprint}",
    "deploy.cd_next_commit": "  Next: commit {path} and push.",
    "deploy.cd_next_run": ("  Then trigger a deploy from the Actions tab on GitHub."),
    "deploy.cd_key_discarded": (
        "Note: the private key was sent to GitHub secrets and discarded "
        "locally. GitHub secrets are write-only — you can't retrieve it later."
    ),
    "deploy.cd_key_recover_hint": (
        "  To keep a local copy on future setup, pass --keep-key PATH. "
        "To rotate and save a copy now, run: aegis deploy-cd-setup --force "
        "--keep-key PATH"
    ),
    "deploy.deploying": "Desplegando en {host}...",
    "deploy.creating_backup": "Creando respaldo {timestamp}...",
    "deploy.backup_failed": "Error al crear respaldo: {error}",
    "deploy.backup_db": "Respaldando base de datos PostgreSQL...",
    "deploy.backup_db_neon": "La base de datos la gestiona Neon (ramas / restauración a un punto en el tiempo); se omite el respaldo local",
    "deploy.backup_db_failed": (
        "Advertencia: Respaldo de base de datos falló, continuando sin él"
    ),
    "deploy.backup_created": "Respaldo creado: {timestamp}",
    "deploy.backup_pruned": "Respaldo antiguo eliminado: {name}",
    "deploy.no_existing": "Sin despliegue existente, omitiendo respaldo",
    "deploy.syncing": "Sincronizando archivos al servidor...",
    "deploy.mkdir_failed": "Error al crear directorio remoto '{path}'",
    "deploy.sync_failed": "Error al sincronizar archivos",
    "deploy.copying_env": "Copiando {file} al servidor como .env...",
    "deploy.env_copy_failed": "Error al copiar archivo .env",
    "deploy.stopping": "Deteniendo servicios existentes...",
    "deploy.building": "Construyendo e iniciando servicios en servidor...",
    "deploy.start_failed": "Error al iniciar servicios",
    "deploy.auto_rollback": "Revirtiendo automáticamente a versión anterior...",
    "deploy.health_waiting": "Esperando estabilización de contenedores...",
    "deploy.health_attempt": "Verificación de salud intento {n}/{total}...",
    "deploy.health_passed": "Verificación de salud aprobada",
    "deploy.health_retry": "Verificación de salud falló, reintentando en {interval}s...",
    "deploy.health_all_failed": "Todas las verificaciones de salud fallaron",
    "deploy.rolled_back": "Revertido a respaldo {timestamp}",
    "deploy.rollback_failed": "¡Reversión falló! Intervención manual requerida.",
    "deploy.health_failed_hint": (
        "Despliegue completado pero verificación de salud falló. Revisa logs con: aegis deploy-logs"
    ),
    "deploy.complete": "¡Despliegue completado!",
    "deploy.rolling_starting": "Despliegue continuo a {host}...",
    "deploy.rolling_building": "Construyendo imagen del servidor web...",
    "deploy.rolling_pausing": "Pausando la cola del worker...",
    "deploy.rolling_pause_failed": (
        "No se pudo activar el indicador de pausa; los workers podrían "
        "recibir SIGTERM en mitad de un job."
    ),
    "deploy.rolling_draining": (
        "Esperando hasta {seconds}s a que los workers se vacíen..."
    ),
    "deploy.rolling_drain_timeout": (
        "Los workers no se vaciaron a tiempo. Indicador de pausa limpiado; abortando."
    ),
    "deploy.rolling_recreating": "Recreando: {services}",
    "deploy.rolling_webserver": (
        "Reinicio continuo del servidor web "
        "(esperando hasta {seconds}s a que esté sano)..."
    ),
    "deploy.rolling_rollout_failed": (
        "docker rollout falló. ¿Está el plugin instalado en "
        "~/.docker/cli-plugins/ en el host de despliegue?"
    ),
    "deploy.rolling_complete": "¡Despliegue continuo completado!",
    "deploy.app_running": "   Aplicación corriendo en: http://{host}",
    "deploy.overseer": "   Dashboard Overseer: http://{host}/dashboard/",
    "deploy.view_logs": "   Ver logs: aegis deploy-logs",
    "deploy.check_status": "   Verificar estado: aegis deploy-status",
    "deploy.backup_complete": "¡Respaldo completado!",
    "deploy.creating_backup_on": "Creando respaldo en {host}...",
    "deploy.no_backups": "Sin respaldos encontrados.",
    "deploy.backups_header": "Respaldos en {host} ({count} total):",
    "deploy.col_timestamp": "Fecha/Hora",
    "deploy.col_size": "Tamaño",
    "deploy.col_database": "Base de datos",
    "deploy.rollback_hint": (
        "Revertir con: aegis deploy-rollback --backup <timestamp>"
    ),
    "deploy.no_backups_available": "Sin respaldos disponibles.",
    "deploy.rolling_back": "Revirtiendo a respaldo {backup} en {host}...",
    "deploy.rollback_not_found": "Respaldo no encontrado: {timestamp}",
    "deploy.rollback_stopping": "Deteniendo servicios...",
    "deploy.rollback_restoring": "Restaurando archivos desde respaldo {timestamp}...",
    "deploy.rollback_restore_failed": "Error al restaurar archivos: {error}",
    "deploy.rollback_db": "Restaurando base de datos...",
    "deploy.rollback_db_neon": "La recuperación de la base de datos la gestiona Neon (ramas / restauración a un punto en el tiempo); se omite la restauración local",
    "deploy.rollback_pg_wait": "Esperando que PostgreSQL esté listo...",
    "deploy.rollback_pg_timeout": (
        "PostgreSQL no quedó listo, intentando restauración de todas formas"
    ),
    "deploy.rollback_db_failed": "Advertencia: Restauración de base de datos falló",
    "deploy.rollback_starting": "Iniciando servicios...",
    "deploy.rollback_start_failed": "Error al iniciar servicios tras reversión",
    "deploy.rollback_complete": "¡Reversión completada!",
    "deploy.rollback_failed_final": "¡Reversión falló!",
    "deploy.status_header": "Estado de servicios en {host}:",
    "deploy.stop_stopping": "Deteniendo servicios...",
    "deploy.stop_success": "Servicios detenidos",
    "deploy.stop_failed": "Error al detener servicios",
    "deploy.restart_restarting": "Reiniciando servicios...",
    "deploy.restart_success": "Servicios reiniciados",
    "deploy.restart_failed": "Error al reiniciar servicios",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": "Ruta al proyecto Aegis Stack (por defecto: directorio actual)",
    "common.help_project_path": "Ruta al proyecto (por defecto: directorio actual)",
    "common.help_yes": "Omitir confirmación",
    "common.help_yes_plural": "Omitir todas las confirmaciones",
    "common.help_interactive_components": "Seleccionar componentes interactivamente",
    "common.help_interactive_services": "Seleccionar servicios interactivamente",
    "common.help_force": "Forzar pese a advertencias de incompatibilidad de versión",
    # ── init CLI help ──────────────────────────────────────────────────
    "blueprints.title": "AVAILABLE BLUEPRINTS",
    "blueprints.none_available": "No blueprints available.",
    "blueprints.includes": "Includes: {names}",
    "blueprints.usage_hint": "Start a project from one:",
    "init.help_opt_blueprint": (
        "Start from a named blueprint (a preset component/service selection)"
    ),
    "init.unknown_blueprint": "Unknown blueprint: {name}. Available: {available}",
    "init.help_arg_name": "Nombre del nuevo proyecto Aegis Stack que se va a crear",
    "init.help_opt_components": "Lista de componentes separada por comas (redis,worker,scheduler,database)",
    "init.help_opt_python": "Versión de Python para el proyecto generado (3.11, 3.12, 3.13 o 3.14)",
    "init.help_opt_force": "Sobrescribir el directorio existente si ya existe",
    "init.help_opt_directory": "Directorio donde se creará el proyecto (por defecto: directorio actual)",
    "init.help_opt_template_version": "Generar desde una versión específica de la plantilla (etiqueta, commit o rama)",
    "init.help_opt_no_llm_sync": "Omitir la sincronización del catálogo de LLM tras generar el proyecto (solo servicio AI)",
    "init.help_opt_dev": "Modo dev: leer plantillas desde el árbol de trabajo (incluye cambios sin commit)",
    "init.help_opt_services": "Servicios: {services}. Opciones de AI: ai[framework,backend,providers] donde framework={frameworks}, backend={backends}, providers={providers}",
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": "Lista de componentes a agregar, separada por comas (scheduler,worker,database)",
    "add.help_opt_scheduler_backend": "Backend del scheduler: 'memory' (por defecto) o 'sqlite' (habilita persistencia)",
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "Actualizar a una versión específica (por defecto: última)",
    "update.help_opt_dry_run": "Previsualizar los cambios sin aplicarlos",
    "update.help_opt_template_path": "Usar una ruta de plantilla personalizada en lugar de la versión instalada",
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": "Lista de componentes a eliminar, separada por comas (scheduler,worker,database)",
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": "Lista de servicios a agregar, separada por comas (auth,ai)",
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": "Lista de servicios a eliminar, separada por comas (auth,ai,comms)",
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": "Nombre de dominio para el certificado TLS (p. ej., example.com)",
    "ingress.help_opt_email": "Correo electrónico para las notificaciones de certificado de Let's Encrypt",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "Dirección IP o nombre de host del servidor",
    "deploy.help_opt_user": "Usuario SSH para el despliegue",
    "deploy.help_opt_path": "Ruta de despliegue en el servidor",
    "deploy.help_opt_public_key": "Ruta a una clave pública que se instalará en authorized_keys del usuario de despliegue (idempotente). Úsala para no tener que ejecutar ssh-copy-id manualmente antes del despliegue.",
    "deploy.help_opt_build": "Construir las imágenes antes de desplegar",
    "deploy.help_opt_backup": "Crear un respaldo antes de desplegar",
    "deploy.help_opt_health": "Ejecutar comprobación de salud tras desplegar",
    "deploy.help_opt_rolling": (
        "Despliegue continuo sin tiempo de inactividad HTTP, solo código. "
        "Rota el servidor web con docker-rollout y pausa la cola del "
        "worker para que los jobs en curso terminen limpiamente. Omite "
        "las migraciones de base de datos."
    ),
    "deploy.help_opt_drain_timeout": (
        "Segundos a esperar a que los workers se vacíen tras pausar la "
        "cola durante un despliegue continuo (por defecto: 90)."
    ),
    "deploy.help_opt_rollout_timeout": (
        "Segundos que docker-rollout espera a que el nuevo servidor web "
        "esté sano durante un despliegue continuo. Ajústalo al "
        "presupuesto del HEALTHCHECK del contenedor (start_period + "
        "retries × interval), no a un reloj de 60s (por defecto: 900)."
    ),
    "deploy.help_opt_rollback_backup": "Marca de tiempo del respaldo al que hacer rollback (por defecto: el más reciente)",
    "deploy.help_opt_logs_follow": "Seguir la salida de los logs en tiempo real",
    "deploy.help_opt_logs_service": "Mostrar los logs de un servicio en concreto",
    "deploy.help_opt_shell_service": "Servicio al que conectarse",
    "deploy.help_opt_gh_repo": "Repositorio de GitHub como owner/name (por defecto: detectar automáticamente desde git remote origin)",
    "deploy.help_opt_gh_tags": "Disparar también el workflow de despliegue al hacer push de tags v*",
    "deploy.help_opt_gh_overwrite": "Sobrescribir los secretos de GitHub y el workflow deploy.yml existentes",
    "deploy.help_opt_dry_run": "Imprimir las acciones planeadas sin realizar cambios",
    "deploy.help_opt_local_key_path": "Ruta donde copiar la clave privada generada antes de la limpieza. Por defecto: sin copia local (la clave solo queda en los secretos de GitHub).",
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "Inspeccionar los plugins de Aegis instalados y buscar en el registro",
    "plugins.cannot_read_answers": "No se pudo leer {path}: {error}. Se omitirán las comprobaciones de compatibilidad.",
    "plugins.help_list": "Listar los plugins instalados y su compatibilidad con este proyecto.",
    "plugins.help_opt_list_project_path": "Proyecto contra el que evaluar la compatibilidad (por defecto: el directorio actual si es un proyecto Aegis).",
    "plugins.help_opt_list_verbose": "Mostrar la columna de descripción.",
    "plugins.section_in_tree": "Incorporados (oficiales)",
    "plugins.section_external": "Plugins externos",
    "plugins.col_name": "Nombre",
    "plugins.col_version": "Versión",
    "plugins.col_kind": "Tipo",
    "plugins.col_description": "Descripción",
    "plugins.col_status": "Estado",
    "plugins.no_external_installed": "No hay plugins externos instalados. Instala uno con: pip install aegis-plugin-<name>",
    "plugins.help_info": "Mostrar información detallada sobre un único plugin.",
    "plugins.help_arg_info_name": "Nombre del plugin (p. ej., 'auth', 'scraper')",
    "plugins.help_opt_info_project_path": "Proyecto contra el que evaluar la compatibilidad.",
    "plugins.not_installed_named": "No hay ningún plugin instalado con el nombre '{name}'.",
    "plugins.available_list": "Disponibles: {names}",
    "plugins.label_first_party": "(oficial)",
    "plugins.label_verified": "(verificado)",
    "plugins.label_unverified": "(comunidad, sin verificar)",
    "plugins.label_kind": "Tipo:",
    "plugins.label_type": "Subtipo:",
    "plugins.label_requires_components": "Requiere comp.:",
    "plugins.label_recommends_components": "Recomienda:",
    "plugins.label_requires_services": "Requiere svcs:",
    "plugins.label_requires_plugins": "Requiere plug.:",
    "plugins.label_conflicts": "Conflictos:",
    "plugins.label_python_deps": "Deps de Python:",
    "plugins.deps_more": "(+{count} más)",
    "plugins.section_options": "Opciones",
    "plugins.option_choices": "valores:",
    "plugins.option_default": "por defecto:",
    "plugins.option_auto_requires": "(con auto_requires)",
    "plugins.info_files": "Archivos: {files}   Migraciones: {migrations} ({tables} tablas)   CLI: {cli}",
    "plugins.cli_yes": "sí",
    "plugins.cli_no": "no",
    "plugins.section_compat": "Compatibilidad",
    "plugins.help_update": "Volver a renderizar las plantillas de un plugin instalado en la versión actualmente instalada vía pip.",
    "plugins.help_arg_update_name": "Plugin que se va a actualizar. Obligatorio salvo que se use --all.",
    "plugins.help_opt_update_all": "Actualizar todos los plugins registrados en _plugins del proyecto.",
    "plugins.help_opt_update_force": "Aplicar la actualización aunque la restricción aegis_version del nuevo plugin excluya la CLI en uso.",
    "plugins.update_need_target": "Indica un nombre de plugin o usa --all.",
    "plugins.update_either_not_both": "Indica un nombre de plugin O --all, no ambos.",
    "plugins.update_no_plugins_installed": "No hay plugins instalados en este proyecto.",
    "plugins.update_not_in_project": "El plugin '{name}' no está instalado en este proyecto.",
    "plugins.update_use_list_hint": "Usa `aegis plugins list` para ver los disponibles y `aegis add <name>` para instalarlos.",
    "plugins.update_not_pip_installed": "El plugin '{name}' figura en la lista _plugins del proyecto, pero no está instalado vía pip; ejecuta primero `pip install aegis-plugin-{name}`.",
    "plugins.update_already_at": "{name} (ya en {version})",
    "plugins.local_changes_replaced": (
        "Replaced {count} locally-modified file(s) owned by '{name}'. "
        "Plugin files are re-rendered on install; your previous versions "
        "were saved to {path}"
    ),
    "plugins.update_forcing": "Forzando actualización pese a la incompatibilidad de versión: {error}",
    "plugins.update_progress": "Actualizando plugin: {name} ({old} → {new})",
    "plugins.update_confirm_apply": "¿Aplicar la actualización a '{name}'?",
    "plugins.update_skipped_by_user": "{name} (omitido por el usuario)",
    "plugins.update_legacy_strings": "Se omiten entradas heredadas de _plugins en formato string: {entries}. Vuelve a agregarlas con `aegis add <name>` para migrar al formato dict actual.",
    "plugins.update_summary_updated": "Actualizados: {count}",
    "plugins.update_summary_skipped": "Omitidos: {count}",
    "plugins.update_summary_failed": "Fallidos: {count}",
    "plugins.help_create": "Generar el andamiaje de un nuevo paquete Python aegis-plugin-<name>.",
    "plugins.help_arg_create_name": "Nombre del plugin (minúsculas, sin guiones). Se convertirá en el paquete Python aegis_plugin_<name> y en el nombre de instalación aegis-plugin-<name>.",
    "plugins.help_opt_create_target": "Directorio padre donde se generará el andamiaje del plugin.",
    "plugins.help_opt_create_author": "Cadena de autor para pyproject.toml y README.",
    "plugins.help_opt_create_description": "Descripción de una línea del plugin.",
    "plugins.create_target_missing": "El directorio de destino no existe: {target}",
    "plugins.create_already_exists": "El directorio ya existe: {output}",
    "plugins.create_pick_different": "Elige otro nombre o elimina el directorio existente.",
    "plugins.create_starting": "Creando plugin: {name}",
    "plugins.create_label_target": "Destino:",
    "plugins.create_label_author": "Autor:",
    "plugins.create_label_description": "Descripción:",
    "plugins.create_default_marker": "(por defecto)",
    "plugins.create_confirm": "¿Generar el andamiaje?",
    "plugins.create_cancelled": "Cancelado.",
    "plugins.create_success": "Se crearon {count} archivos en {output}",
    "plugins.create_next_steps_header": "Siguientes pasos:",
    "plugins.create_next_steps_confirm_comment": "comprueba que el plugin se detecta",
    "plugins.create_next_steps_edit_comment": "edita src/aegis_plugin_<name>/plugin.py para añadir el cableado",
    "plugins.help_search": "Buscar en el registro oficial de plugins.",
    "plugins.help_arg_search_keyword": "Palabra clave de búsqueda opcional",
    "plugins.search_not_available": "El registro de plugins aún no está disponible.",
    "plugins.search_install_hint": "Por ahora: pip install aegis-plugin-<name>, luego aegis plugins list.",
    "plugins.search_future_keyword": "Cuando el registro esté disponible, este comando buscará '{keyword}'.",
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "Aplicaciones Python listas para producción desde el primer día.",
    "guided.welcome.body": "Esta configuración guiada recorre cada bloque de construcción con una breve explicación para que decidas qué necesita tu proyecto. Elige solo lo que quieras ahora; todo lo demás puede añadirse después con 'aegis add'.",
    "guided.corestack.title": "INCLUIDO EN TODOS LOS PROYECTOS",
    "guided.corestack.body": "Todo proyecto de Aegis empieza con estos dos, conectados entre sí y listos para ejecutarse.",
    "guided.sidebar.components": "COMPONENTES",
    "guided.sidebar.services": "SERVICIOS",
    "guided.prompt.worker_backend": "Elige un backend de worker",
    "guided.prompt.scheduler_backend": "Persistencia del programador: ¿conservar el historial de tareas entre reinicios?",
    "guided.prompt.database_engine": "Motor de base de datos para {context}",
    "guided.prompt.postgres_provider": "Host de PostgreSQL para {context}",
    "guided.prompt.auth_level": "Nivel de autenticación",
    "guided.prompt.ai_framework": "Framework de IA",
    "guided.prompt.ai_providers": "Proveedores de IA: elige los que quieras integrar",
    "guided.prompt.ai_storage": "Almacenamiento de conversaciones de IA",
    "guided.prompt.ai_rag": "Añadir RAG: ¿chat basado en tus propios documentos y código?",
    "guided.prompt.ai_voice": "Añadir voz: ¿texto a voz y voz a texto?",
    "guided.note.one_datastore": "Un almacén de datos por proyecto: el motor que elijas aquí define la base de datos del proyecto, compartida por todo lo demás que guarde datos.",
    "guided.note.one_database_host": "Una base de datos por proyecto: este host sirve a todo lo que guarda datos.",
    "guided.multi.hint": "Marca tantos como quieras y luego elige Continuar.",
    "guided.choice.add": "Añadir",
    "guided.choice.skip": "Omitir",
    "guided.screen.add_question": "¿Añadir {name}?",
    "guided.screen.too_small": "Terminal demasiado pequeña. Amplíala al menos a {w}x{h}.",
    "guided.review.title": "TU CONFIGURACIÓN",
    "guided.review.files_pane": "ARCHIVOS DE COMPONENTES",
    "guided.review.deps_pane": "DEPENDENCIAS",
    "guided.review.counts": "{files} archivos de componentes · {deps} dependencias",
    "guided.building.title": "Generando {name} …",
    "guided.building.preparing": "Preparando …",
    "guided.building.note": "Esto puede tardar uno o dos minutos; uv hace el trabajo pesado.",
    "guided.hint.building": "generando …",
    "guided.done.ready": "{name} está listo",
    "guided.done.body": "Proyecto generado y dependencias instaladas.",
    "guided.done.next_steps": "PRÓXIMOS PASOS",
    "guided.done.project_structure": "ESTRUCTURA DEL PROYECTO",
    "guided.done.recreate": "RECREA ESTA CONFIGURACIÓN EN CUALQUIER MOMENTO",
    "guided.done.copy_note": "Pulsa c para copiar; el comando completo también aparecerá abajo al terminar.",
    "guided.done.copied": "Copiado al portapapeles ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "Continuar",
    "guided.header.label": "configuración guiada",
    "guided.hint.move": "mover",
    "guided.hint.select": "seleccionar",
    "guided.hint.toggle": "alternar",
    "guided.hint.back": "atrás",
    "guided.hint.begin": "empezar",
    "guided.hint.build": "generar",
    "guided.hint.next": "siguiente",
    "guided.hint.finish": "finalizar",
    "guided.hint.quit": "salir",
    "guided.hint.services": "ir a servicios",
    "guided.hint.copy": "copiar comando",
    "guided.hint.deps": "dependencias",
    "guided.hint.files": "archivos",
    "guided.review.core": "Núcleo:",
    "guided.review.infrastructure": "Infraestructura:",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "Servicios:",
    "guided.review.auto": "auto",
    "guided.review.build": "Generar {name}",
    "guided.review.more": "… +{n} más",
    "guided.screen.requires": "Requiere:",
    "guided.screen.added_automatically": "(añadido automáticamente)",
    "guided.screen.pairs": "Combina bien con:",
    "guided.screen.docs": "Docs:",
    "component.backend.long": "Una aplicación FastAPI que sirve tu API, asíncrona desde la base: rutas tipadas, documentación OpenAPI automática, comprobaciones de estado y un conjunto de pruebas que ya lo cubre todo.",
    "component.frontend.long": "Un panel de Flet que muestra el estado del sistema en tiempo real y el de cada componente que elijas aquí, listo para ampliarse con tus propias vistas. Python de principio a fin, sin cadena de compilación de JavaScript.",
    "component.worker.long": "Procesamiento de tareas en segundo plano con el backend que elijas: arq (por defecto), Dramatiq o TaskIQ. Descarga el trabajo lento como correos, exportaciones y llamadas a API de terceros para que las peticiones sigan siendo rápidas. Funciona sobre Redis, que se añade automáticamente.",
    "component.scheduler.long": "Programación de tareas en segundo plano y trabajos cron con APScheduler. Ejecuta trabajo periódico como limpiezas, informes y comprobaciones de estado según un horario. La persistencia opcional en base de datos conserva el historial de tareas y sobrevive a los reinicios.",
    "component.database.long": "Almacenamiento persistente con el ORM SQLModel, migraciones de Alembic y agrupación de conexiones. SQLite te da una base de datos en archivo sin configuración para desarrollo; PostgreSQL es el camino a producción. La mayoría de los servicios se apoyan en esto.",
    "component.redis.long": "Almacén de datos en memoria que actúa como caché y agente de mensajes. Impulsa las colas de tareas en segundo plano y la mensajería pub/sub entre tus servicios, y ofrece a los manejadores de peticiones una caché compartida y rápida.",
    "component.ingress.long": "Proxy inverso y enrutamiento de tráfico con Traefik: descubrimiento automático de servicios, protección de endpoints de administración y TLS opcional mediante Let's Encrypt. La puerta de entrada para los despliegues.",
    "component.observability.long": "Trazado distribuido, métricas y correlación de registros con Pydantic Logfire. Instrumenta tu aplicación automáticamente y se adapta a los componentes que actives, para que veas qué está haciendo realmente producción.",
    "component.storage.long": "An S3 backend for the object store every stack already has: documents, chat attachments, anything addressed by its content hash. Talks to any S3-compatible endpoint; the dev stack ships SeaweedFS in a container. Switching from the filesystem is a byte copy, never a migration.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "Gestión completa de usuarios con autenticación JWT, cookies de sesión y rotación de tokens de actualización. Tres niveles: correo/contraseña básico, roles y permisos RBAC, u organizaciones multiinquilino. Incluye registro, inicio de sesión y una pestaña de panel de administración.",
    "service.ai.long": "Una plataforma de IA completa: chat multiproveedor, un catálogo de LLM con unos 2000 modelos, seguimiento de costes con analíticas de uso, RAG opcional para conversaciones que conocen tu código y voz opcional (TTS/STT). Elige Pydantic AI o LangChain como framework.",
    "service.comms.long": "Correo, SMS y llamadas de voz con proveedores del sector: Resend para correo, Twilio para SMS y voz. Ambos tienen planes gratuitos, así que puedes empezar sin tarjeta de crédito.",
    "service.insights.long": "Seguimiento automático de la adopción de tu proyecto en GitHub, PyPI, Plausible Analytics y Reddit. Recopila según un horario, guarda el historial y visualiza el crecimiento en el panel.",
    "service.payment.long": "Procesamiento de pagos con Stripe: sesiones de pago, suscripciones, webhooks y reembolsos. El modo de prueba de Stripe no necesita tarjeta de crédito, así que puedes construir todo el flujo antes de salir a producción.",
    "service.documents.long": "Durable storage for the paper an application accumulates: scans, statements, letters, forms. Bytes are addressed by their own content hash, so the same file uploaded twice is one document and one object, and moving to a bucket later is a copy rather than a migration.",
    "service.blog.long": "Publicación nativa en Markdown con entradas respaldadas por base de datos, etiquetas, borradores y una interfaz de editor en el panel. Importa y exporta entradas como Markdown plano con frontmatter.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "En memoria",
    "guided.choice.scheduler.memory": "Sin persistencia. Las tareas se reinician al reiniciar — omite si no estás seguro.",
    "guided.choice.scheduler.sqlite": "Conserva el historial de tareas en una base de datos en archivo.",
    "guided.choice.scheduler.postgres": "Conserva el historial de tareas, de nivel de producción.",
    "guided.choice.worker.arq": "Worker asíncrono sencillo y bien probado con configuración mínima. Ideal para tareas con uso intensivo de E/S. El predeterminado.",
    "guided.choice.worker.dramatiq": "Modelo de actores multiproceso. Ideal para tareas con uso intensivo de CPU que se benefician de varios procesos del sistema.",
    "guided.choice.worker.taskiq": "Asíncrono nativo, con brokers por cola y transporte Redis Streams con confirmaciones.",
    "guided.choice.db.sqlite": "Base de datos en archivo sin configuración. Estupenda para desarrollo.",
    "guided.choice.db.postgres": "De nivel de producción, con conexiones agrupadas.",
    "guided.choice.db_provider.container": "Contenedor postgres:16 local, dev y prod.",
    "guided.choice.db_provider.neon": (
        "Postgres serverless: cloud en prod, contenedor local en dev."
    ),
    "guided.choice.auth.basic": "Correo y contraseña con sesiones JWT.",
    "guided.choice.auth.rbac": "Añade roles y permisos.",
    "guided.choice.auth.org": "Organizaciones multiinquilino.",
    "guided.choice.framework.pydantic_ai": "Tipado y ligero. El predeterminado.",
    "guided.choice.framework.langchain": "Ecosistema amplio, muchas integraciones.",
    "guided.choice.storage.memory": "Sin historial, nada que configurar.",
    "guided.choice.storage.sqlite": "Historial de chat persistente en una base de datos en archivo.",
    "guided.choice.storage.postgres": "Persistente y de nivel de producción.",
    "guided.choice.provider.public.desc": "Endpoint público gratuito",
    "guided.choice.provider.public.pricing": "Gratis, sin clave de API",
    "guided.choice.provider.openai.desc": "Modelos GPT",
    "guided.choice.provider.openai.pricing": "De pago",
    "guided.choice.provider.anthropic.desc": "Modelos Claude",
    "guided.choice.provider.anthropic.pricing": "De pago",
    "guided.choice.provider.google.desc": "Modelos Gemini",
    "guided.choice.provider.google.pricing": "Plan gratuito (solo Flash)",
    "guided.choice.provider.groq.desc": "Inferencia rápida",
    "guided.choice.provider.groq.pricing": "Plan gratuito",
    "guided.choice.provider.mistral.desc": "Modelos abiertos",
    "guided.choice.provider.mistral.pricing": "Mayormente de pago",
    "guided.choice.provider.cohere.desc": "Enfoque empresarial",
    "guided.choice.provider.cohere.pricing": "Gratis limitado",
    "guided.choice.provider.ollama.desc": "Inferencia local",
    "guided.choice.provider.ollama.pricing": "Gratis (local)",
    "build.step.render": "Generando archivos del proyecto",
    "build.step.deps": "Instalando dependencias",
    "build.step.env": "Configuración del entorno",
    "build.step.migrate": "Aplicando migraciones",
    "build.step.llm": "Sincronizando catálogo de LLM",
    "build.step.format": "Formateando el código",
}
