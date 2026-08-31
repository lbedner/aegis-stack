"""Russian locale — Определения сообщений на русском языке."""

MESSAGES: dict[str, str] = {
    # ── Валидация ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "Недопустимое имя проекта. Разрешены только буквы, цифры, "
        "дефисы и символы подчёркивания."
    ),
    "validation.reserved_name": "«{name}» — зарезервированное имя.",
    "validation.name_too_long": ("Имя проекта слишком длинное. Максимум 50 символов."),
    "validation.invalid_python": (
        "Недопустимая версия Python «{version}». Допустимые: {supported}"
    ),
    "validation.unknown_service": "Неизвестный сервис: {name}",
    "validation.unknown_services": "Неизвестные сервисы: {names}",
    "validation.unknown_component": "Неизвестный компонент: {name}",
    # ── Команда init ──────────────────────────────────────────────────
    "init.title": "Aegis Stack — Инициализация проекта",
    "init.location": "Расположение:",
    "init.template_version": "Версия шаблона:",
    "init.dir_exists": "Каталог «{path}» уже существует",
    "init.dir_exists_hint": "Используйте --force для перезаписи или выберите другое имя",
    "init.overwriting": "Перезапись каталога: {path}",
    "init.services_require": "Сервисы требуют компоненты: {components}",
    "init.compat_errors": "Ошибки совместимости сервисов и компонентов:",
    "init.suggestion_add": (
        "Рекомендация: добавьте недостающие компоненты --components {components}"
    ),
    "init.suggestion_remove": (
        "Или уберите --components, чтобы сервисы сами добавили зависимости."
    ),
    "init.suggestion_interactive": (
        "Также можно использовать интерактивный режим для автоматического добавления зависимостей."
    ),
    "init.auto_detected_scheduler": (
        "Обнаружено автоматически: планировщик с хранилищем {backend}"
    ),
    "init.auto_added_deps": "Автоматически добавлены зависимости: {deps}",
    "init.auto_added_by_services": "Добавлено сервисами автоматически:",
    "init.required_by": "требуется для {services}",
    "init.config_title": "Конфигурация проекта",
    "init.config_name": "Имя:",
    "init.config_core": "Ядро:",
    "init.config_infra": "Инфраструктура:",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "Сервисы:",
    "init.component_files": "Файлы компонентов:",
    "init.entrypoints": "Точки входа:",
    "init.worker_queues": "Очереди задач:",
    "init.dependencies": "Устанавливаемые зависимости:",
    "init.confirm_create": "Создать проект?",
    "init.cancelled": "Создание проекта отменено",
    "init.removing_dir": "Удаление каталога: {path}",
    "init.creating": "Создание проекта: {name}",
    "init.error": "Ошибка создания проекта: {error}",
    "init.replay_hint": "Пересоздайте этот стек в любое время:",
    # ── Интерактив: заголовки разделов ─────────────────────────────────
    "interactive.component_selection": "Выбор компонентов",
    "interactive.service_selection": "Выбор сервисов",
    "interactive.core_included": (
        "Базовые компоненты ({components}) включены автоматически"
    ),
    "interactive.infra_header": "Компоненты инфраструктуры:",
    "interactive.services_intro": (
        "Сервисы предоставляют бизнес-логику для вашего приложения."
    ),
    # ── Описания компонентов ────────────────────────────────────────────
    "component.backend": "FastAPI backend-сервер",
    "component.frontend": "Flet интерфейс",
    "component.redis": "Redis — кеш и брокер сообщений",
    "component.worker": "Фоновая обработка задач (arq, Dramatiq или TaskIQ)",
    "component.scheduler": "Инфраструктура планирования задач",
    "component.database": "База данных с SQLModel ORM (SQLite или PostgreSQL)",
    "component.ingress": "Traefik — обратный прокси и балансировщик",
    "component.observability": "Logfire — наблюдаемость, трассировка и метрики",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Описания сервисов ──────────────────────────────────────────────
    "service.auth": "Аутентификация и авторизация с JWT-токенами",
    "service.ai": "AI-чатбот с поддержкой нескольких фреймворков",
    "service.comms": "Сервис коммуникаций: email, SMS и голос",
    "service.blog": "Markdown-блог с черновиками, публикацией и тегами",
    # ── Интерактив: запросы для компонентов ─────────────────────────────
    "interactive.add_prompt": "Добавить {description}?",
    "interactive.add_with_redis": "Добавить {description}? (Redis будет добавлен автоматически)",
    "interactive.worker_configured": "Worker с backend {backend} настроен",
    # ── Интерактив: планировщик ────────────────────────────────────────
    "interactive.scheduler_persistence": "Хранение данных планировщика:",
    "interactive.persist_prompt": (
        "Сохранять данные запланированных задач? "
        "(история задач, восстановление после перезапуска)"
    ),
    "interactive.scheduler_db_configured": "Планировщик + БД {engine} настроены",
    "interactive.bonus_backup": "Бонус: добавлена задача резервного копирования БД",
    "interactive.backup_desc": ("Ежедневное резервное копирование БД (запуск в 2:00)"),
    # ── Интерактив: движок БД ──────────────────────────────────────────
    "interactive.db_engine_label": "Движок БД для {context}:",
    "interactive.db_select": "Выберите движок базы данных:",
    "interactive.db_sqlite": "SQLite — простая, файловая (для разработки)",
    "interactive.db_postgres": (
        "PostgreSQL — продакшн, поддержка нескольких контейнеров"
    ),
    "interactive.db_reuse": "Используется ранее выбранная БД: {engine}",
    "interactive.db_provider_select": "Выберите хост PostgreSQL:",
    "interactive.db_provider_container": (
        "Локальный контейнер - postgres:16 в Docker (dev и prod)"
    ),
    "interactive.db_provider_neon": (
        "Neon - бессерверный Postgres (облако для prod, локальный контейнер в dev)"
    ),
    # ── Интерактив: backend воркера ────────────────────────────────────
    "interactive.worker_label": "Backend воркера:",
    "interactive.worker_select": "Выберите backend воркера:",
    "interactive.worker_arq": "arq — асинхронный, лёгкий (по умолчанию)",
    "interactive.worker_dramatiq": ("Dramatiq — процессный, для CPU-нагрузок"),
    "interactive.worker_taskiq": ("TaskIQ — асинхронный, брокеры для каждой очереди"),
    # ── Интерактив: аутентификация ─────────────────────────────────────
    "interactive.auth_header": "Сервисы аутентификации:",
    "interactive.auth_level_label": "Уровень аутентификации:",
    "interactive.auth_select": "Какой тип аутентификации?",
    "interactive.auth_basic": "Базовый — вход по email/паролю",
    "interactive.auth_rbac": "С ролями — + ролевой доступ (экспериментально)",
    "interactive.auth_org": "С организациями — + мультитенантность (экспериментально)",
    "interactive.auth_selected": "Выбран уровень: {level}",
    "interactive.auth_db_required": "Требуется БД:",
    "interactive.auth_db_reason": (
        "Аутентификация требует базу данных для хранения пользователей"
    ),
    "interactive.auth_db_details": "(аккаунты, сессии, JWT-токены)",
    "interactive.auth_db_already": "Компонент БД уже выбран",
    "interactive.auth_db_confirm": "Продолжить и добавить компонент БД?",
    "interactive.auth_cancelled": "Сервис аутентификации отменён",
    "interactive.auth_db_configured": "Аутентификация + БД настроены",
    # ── Интерактив: AI-сервис ──────────────────────────────────────────
    "interactive.ai_header": "Сервисы AI и машинного обучения:",
    "interactive.ai_framework_label": "Выбор AI-фреймворка:",
    "interactive.ai_framework_intro": "Выберите AI-фреймворк:",
    "interactive.ai_pydanticai": (
        "PydanticAI — типобезопасный, Pythonic (рекомендуется)"
    ),
    "interactive.ai_langchain": ("LangChain — популярный, множество интеграций"),
    "interactive.ai_use_pydanticai": "Использовать PydanticAI? (рекомендуется)",
    "interactive.ai_selected_framework": "Выбран фреймворк: {framework}",
    "interactive.ai_tracking_context": "Отслеживание использования AI",
    "interactive.ai_tracking_label": "Отслеживание LLM:",
    "interactive.ai_tracking_prompt": (
        "Включить отслеживание? (токены, стоимость, история диалогов)"
    ),
    "interactive.ai_sync_label": "Синхронизация каталога LLM:",
    "interactive.ai_sync_desc": (
        "Синхронизация загружает данные моделей из API OpenRouter/LiteLLM"
    ),
    "interactive.ai_sync_time": ("Требуется сетевой доступ, занимает ~30–60 секунд"),
    "interactive.ai_sync_prompt": "Синхронизировать каталог LLM при генерации проекта?",
    "interactive.ai_sync_will": "Каталог LLM будет синхронизирован после генерации",
    "interactive.ai_sync_skipped": (
        "Синхронизация LLM пропущена — доступны статические данные"
    ),
    "interactive.ai_provider_label": "Выбор AI-провайдера:",
    "interactive.ai_provider_intro": ("Выберите AI-провайдеров (множественный выбор)"),
    "interactive.ai_provider_options": "Варианты провайдеров:",
    "interactive.ai_provider_recommended": "(Рекомендуется)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI — модели GPT (платно)",
    "interactive.ai_provider.anthropic": "Anthropic — модели Claude (платно)",
    "interactive.ai_provider.google": "Google — модели Gemini (бесплатный тариф)",
    "interactive.ai_provider.groq": "Groq — быстрый инференс (бесплатный тариф)",
    "interactive.ai_provider.mistral": "Mistral — открытые модели (в основном платно)",
    "interactive.ai_provider.cohere": "Cohere — корпоративный (ограниченный бесплатный)",
    "interactive.ai_provider.ollama": "Ollama — локальный инференс (бесплатно)",
    "interactive.ai_no_providers": (
        "Провайдеры не выбраны, добавляются рекомендуемые..."
    ),
    "interactive.ai_selected_providers": "Выбранные провайдеры: {providers}",
    "interactive.ai_deps_optimized": ("Зависимости будут оптимизированы под ваш выбор"),
    "interactive.ai_ollama_label": "Режим развёртывания Ollama:",
    "interactive.ai_ollama_intro": "Как запускать Ollama?",
    "interactive.ai_ollama_host": (
        "Host — подключение к Ollama на вашей машине (Mac/Windows)"
    ),
    "interactive.ai_ollama_docker": (
        "Docker — запуск Ollama в контейнере (Linux/Deploy)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "Подключиться к Ollama на хосте? (рекомендуется для Mac/Windows)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama будет подключаться к host.docker.internal:11434"
    ),
    "interactive.ai_ollama_host_hint": "Убедитесь, что Ollama запущен: ollama serve",
    "interactive.ai_ollama_docker_ok": (
        "Сервис Ollama будет добавлен в docker-compose.yml"
    ),
    "interactive.ai_ollama_docker_hint": (
        "Примечание: первый запуск может занять время для загрузки моделей"
    ),
    "interactive.ai_rag_label": "RAG (Retrieval-Augmented Generation):",
    "interactive.ai_rag_prompt": (
        "Включить RAG для индексации документов и семантического поиска?"
    ),
    "interactive.ai_rag_enabled": "RAG включён с векторным хранилищем ChromaDB",
    "interactive.ai_voice_label": "Голос (Text-to-Speech и Speech-to-Text):",
    "interactive.ai_voice_prompt": ("Включить голосовые возможности? (TTS и STT)"),
    "interactive.ai_voice_enabled": "Голос включён: TTS и STT",
    "interactive.ai_db_already": "БД уже выбрана — отслеживание включено",
    "interactive.ai_db_added": "БД ({backend}) добавлена для отслеживания",
    "interactive.ai_configured": "AI-сервис настроен",
    # ── Общее: валидация ───────────────────────────────────────────────
    "shared.not_copier_project": "Проект в {path} не создан через Copier.",
    "shared.copier_only": (
        "Команда «aegis {command}» работает только с проектами, созданными через Copier."
    ),
    "shared.regenerate_hint": (
        "Для добавления компонентов пересоздайте проект с нужными компонентами."
    ),
    "shared.git_not_initialized": "Проект не находится в git-репозитории",
    "shared.git_required": "Обновления через Copier требуют git для отслеживания изменений",
    "shared.git_init_hint": (
        "Проекты, созданные через «aegis init», должны иметь git автоматически"
    ),
    "shared.git_manual_init": (
        "Если проект создан вручную, выполните: "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "Пустое имя компонента недопустимо",
    "shared.empty_service": "Пустое имя сервиса недопустимо",
    # ── Общее: следующие шаги / ревью ──────────────────────────────────
    "shared.next_steps": "Следующие шаги:",
    "shared.next_make_check": "   1. Выполните «make check» для проверки обновления",
    "shared.next_test": "   2. Протестируйте приложение",
    "shared.next_commit": "   3. Закоммитьте изменения: git add . && git commit",
    "shared.review_header": "Просмотрите изменения:",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "Операция отменена",
    "shared.interactive_ignores_args": (
        "Предупреждение: флаг --interactive игнорирует аргументы компонентов"
    ),
    "shared.no_components_selected": "Компоненты не выбраны",
    "shared.no_services_selected": "Сервисы не выбраны",
    # ── Команда add ───────────────────────────────────────────────────
    "add.title": "Aegis Stack — Добавление компонентов",
    "add.project": "Проект: {path}",
    "add.error_no_args": ("Ошибка: требуется аргумент components (или --interactive)"),
    "add.usage_hint": "Использование: aegis add scheduler,worker",
    "add.interactive_hint": "Или: aegis add --interactive",
    "add.auto_added_deps": "Автоматически добавлены зависимости: {deps}",
    "add.validation_failed": "Ошибка валидации компонентов: {error}",
    "add.load_config_failed": "Не удалось загрузить конфигурацию проекта: {error}",
    "add.already_enabled": "Уже включены: {components}",
    "add.all_enabled": "Все запрошенные компоненты уже включены!",
    "add.components_to_add": "Добавляемые компоненты:",
    "add.scheduler_backend": "Backend планировщика: {backend}",
    "add.confirm": "Добавить эти компоненты?",
    "add.updating": "Обновление проекта...",
    "add.adding": "Добавление {component}...",
    "add.added_files": "Добавлено файлов: {count}",
    "add.skipped_files": "Пропущено файлов: {count}",
    "add.success": "Компоненты добавлены!",
    "add.failed_component": "Не удалось добавить {component}: {error}",
    "add.failed": "Не удалось добавить компоненты: {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "Неверный формат компонента: {error}",
    "add.bracket_override": (
        "Синтаксис 'scheduler[{engine}]' переопределяет --backend {backend}"
    ),
    "add.invalid_scheduler_backend": "Недопустимый backend планировщика: «{backend}»",
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "Допустимые варианты: {options}",
    "add.postgres_coming": "Примечание: поддержка PostgreSQL появится в будущих версиях",
    "add.auto_added_db": "Автоматически добавлен компонент БД для хранения данных планировщика",
    "add.generated_migration": "Создана миграция: {name}",
    "add.scheduler_db_engine_mismatch": "Невозможно использовать бэкенд планировщика '{backend}': движок базы данных проекта — '{engine}'. Они должны совпадать.",
    # ── Команда remove ────────────────────────────────────────────────
    "remove.title": "Aegis Stack — Удаление компонентов",
    "remove.project": "Проект: {path}",
    "remove.error_no_args": (
        "Ошибка: требуется аргумент components (или --interactive)"
    ),
    "remove.usage_hint": "Использование: aegis remove scheduler,worker",
    "remove.interactive_hint": "Или: aegis remove --interactive",
    "remove.no_selected": "Компоненты для удаления не выбраны",
    "remove.validation_failed": "Ошибка валидации компонентов: {error}",
    "remove.load_config_failed": "Не удалось загрузить конфигурацию проекта: {error}",
    "remove.cannot_remove_core": "Невозможно удалить базовый компонент: {component}",
    "remove.not_enabled": "Не включены: {components}",
    "remove.nothing_to_remove": "Нечего удалять!",
    "remove.auto_remove_redis": (
        "Автоудаление redis (не имеет самостоятельной функции, нужен только worker)"
    ),
    "remove.scheduler_persistence_warn": "ВАЖНО: Предупреждение о хранилище планировщика",
    "remove.scheduler_persistence_detail": (
        "Планировщик использует SQLite для хранения задач."
    ),
    "remove.scheduler_db_remains": ("Файл БД data/scheduler.db останется на месте."),
    "remove.scheduler_keep_hint": (
        "Чтобы сохранить историю задач: оставьте компонент БД"
    ),
    "remove.scheduler_remove_hint": (
        "Чтобы удалить все данные: удалите также компонент БД"
    ),
    "remove.components_to_remove": "Удаляемые компоненты:",
    "remove.warning_delete": ("ВНИМАНИЕ: файлы компонентов будут УДАЛЕНЫ из проекта!"),
    "remove.commit_hint": "Убедитесь, что изменения закоммичены в git.",
    "remove.confirm": "Удалить эти компоненты?",
    "remove.removing_all": "Удаление компонентов...",
    "remove.removing": "Удаление {component}...",
    "remove.removed_files": "Удалено файлов: {count}",
    "remove.failed_component": "Не удалось удалить {component}: {error}",
    "remove.success": "Компоненты удалены!",
    "remove.failed": "Не удалось удалить компоненты: {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Ручной updater ─────────────────────────────────────────────────
    "updater.processing_files": "Обработка файлов компонентов: {count}...",
    "updater.updating_shared": "Обновление общих файлов шаблонов...",
    "updater.shared_preserved": "Локальные изменения сохранены (перегенерация пропущена, объедините вручную): {file}",
    "updater.shared_merged": "Изменения шаблона объединены с вашим настроенным файлом: {file}",
    "updater.shared_conflict": "Конфликт слияния (маркеры записаны, разрешите вручную): {file}",
    "updater.running_postgen": "Выполнение пост-генерационных задач...",
    "updater.deps_synced": "Зависимости синхронизированы (uv sync)",
    "updater.code_formatted": "Код отформатирован (make fix)",
    # ── Карта проекта ─────────────────────────────────────────────────
    "projectmap.new": "НОВОЕ",
    # ── Пост-генерация: настройка ─────────────────────────────────────
    "postgen.setup_start": "Настройка окружения проекта...",
    "postgen.deps_installing": "Установка зависимостей через uv...",
    "postgen.deps_success": "Зависимости установлены",
    "postgen.deps_failed": "Генерация проекта не удалась: ошибка установки зависимостей",
    "postgen.deps_failed_detail": (
        "Файлы проекта на месте, но проект не готов к использованию."
    ),
    "postgen.deps_failed_hint": (
        "Исправьте проблему с зависимостями (проверьте совместимость версии Python) и повторите."
    ),
    "postgen.deps_warn_failed": "Внимание: установка зависимостей не удалась",
    "postgen.deps_manual": "Выполните «uv sync» вручную после создания проекта",
    "postgen.deps_timeout": (
        "Внимание: таймаут установки зависимостей — выполните «uv sync» вручную"
    ),
    "postgen.deps_uv_missing": "Внимание: uv не найден в PATH",
    "postgen.deps_uv_install": "Установите uv: https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "Внимание: установка зависимостей не удалась: {error}",
    "postgen.env_setup": "Настройка окружения...",
    "postgen.env_created": "Файл окружения создан из .env.example",
    "postgen.env_exists": "Файл окружения уже существует",
    "postgen.env_missing": "Внимание: файл .env.example не найден",
    "postgen.env_error": "Внимание: ошибка настройки окружения: {error}",
    "postgen.env_manual": "Скопируйте .env.example в .env вручную",
    # ── Пост-генерация: БД/миграции ────────────────────────────────────
    "postgen.db_setup": "Настройка схемы БД...",
    "postgen.db_success": "Таблицы БД созданы",
    "postgen.db_alembic_missing": "Внимание: конфиг Alembic не найден по пути {path}",
    "postgen.db_alembic_hint": (
        "Миграция пропущена. Убедитесь, что конфиг существует, "
        "и выполните «alembic upgrade head» вручную."
    ),
    "postgen.db_failed": "Внимание: настройка миграций не удалась",
    "postgen.db_manual": "Выполните «alembic upgrade head» вручную после создания проекта",
    "postgen.db_timeout": (
        "Внимание: таймаут миграции — выполните «alembic upgrade head» вручную"
    ),
    "postgen.db_error": "Внимание: ошибка миграции: {error}",
    # ── Пост-генерация: LLM-фикстуры/синхронизация ────────────────────
    "postgen.llm_seeding": "Загрузка LLM-фикстур...",
    "postgen.llm_seed_success": "LLM-фикстуры загружены",
    "postgen.llm_seed_failed": "Внимание: загрузка LLM-фикстур не удалась",
    "postgen.llm_seed_manual": (
        "Фикстуры можно загрузить вручную через загрузчик фикстур"
    ),
    "postgen.llm_seed_timeout": "Внимание: таймаут загрузки LLM-фикстур",
    "postgen.llm_seed_error": "Внимание: ошибка загрузки LLM-фикстур: {error}",
    "postgen.llm_syncing": "Синхронизация каталога LLM из внешних API...",
    "postgen.llm_sync_success": "Каталог LLM синхронизирован",
    "postgen.llm_sync_failed": "Внимание: синхронизация каталога LLM не удалась",
    "postgen.llm_sync_manual": (
        "Выполните «{slug} llm sync» вручную для заполнения каталога"
    ),
    "postgen.llm_sync_timeout": "Внимание: таймаут синхронизации каталога LLM",
    "postgen.llm_sync_error": "Внимание: ошибка синхронизации каталога LLM: {error}",
    # ── Пост-генерация: форматирование ─────────────────────────────────
    "postgen.format_timeout": (
        "Внимание: таймаут форматирования — выполните «make fix» вручную"
    ),
    "postgen.format_error": "Внимание: автоформатирование пропущено: {error}",
    "postgen.format_error_manual": "Выполните «make fix» вручную для форматирования",
    "postgen.format_start": "Форматирование сгенерированного кода...",
    "postgen.format_success": "Форматирование завершено",
    "postgen.format_partial": ("Обнаружены замечания форматирования, но проект создан"),
    "postgen.format_manual": "Выполните «make fix» для исправления оставшихся замечаний",
    "postgen.format_hint": "Выполните «make fix» для форматирования кода",
    "postgen.llm_sync_skipped": "Синхронизация каталога LLM пропущена",
    "postgen.llm_fixtures_outdated": "Загружены статические фикстуры (могут быть устаревшими)",
    "postgen.llm_sync_hint": "Выполните «{slug} llm sync» позже для получения свежих данных",
    "postgen.llm_fixtures_fallback": (
        "Статические фикстуры доступны, но могут быть устаревшими"
    ),
    "postgen.ready": "Проект готов к запуску!",
    "postgen.next_steps": "Следующие шаги:",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Открыть Overseer: http://localhost:8000/dashboard/",
    # ── Пост-генерация: карта проекта ──────────────────────────────────
    "projectmap.title": "Структура проекта:",
    "projectmap.components": "Компоненты",
    "projectmap.services": "Бизнес-логика",
    "projectmap.models": "Модели БД",
    "projectmap.cli": "CLI-команды",
    "projectmap.entrypoints": "Точки запуска",
    "projectmap.tests": "Тесты",
    "projectmap.migrations": "Миграции",
    "projectmap.auth": "Аутентификация",
    "projectmap.ai": "AI-диалоги",
    "projectmap.comms": "Коммуникации",
    "projectmap.insights": "Adoption metrics",
    "projectmap.payment": "Payments and subscriptions",
    "projectmap.blog": "Markdown blog",
    "projectmap.finance": "Personal finance",
    "projectmap.docs": "Документация",
    # ── Пост-генерация: подвал ─────────────────────────────────────────
    "postgen.docs_link": "Документация: https://docs.aegis-stack.io",
    "postgen.star_prompt": ("Если Aegis Stack оказался полезен, поставьте звёздочку:"),
    # ── Команда add-service ────────────────────────────────────────────
    "add_service.title": "Aegis Stack — Добавление сервисов",
    "add_service.project": "Проект: {path}",
    "add_service.error_no_args": (
        "Ошибка: требуется аргумент services (или --interactive)"
    ),
    "add_service.usage_hint": "Использование: aegis add-service auth,ai",
    "add_service.interactive_hint": "Или: aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "Предупреждение: флаг --interactive игнорирует аргументы сервисов"
    ),
    "add_service.no_selected": "Сервисы не выбраны",
    "add_service.already_enabled": "Уже включены: {services}",
    "add_service.all_enabled": "Все запрошенные сервисы уже включены!",
    "add_service.validation_failed": "Ошибка валидации сервисов: {error}",
    "add_service.load_config_failed": "Не удалось загрузить конфигурацию проекта: {error}",
    "add_service.services_to_add": "Добавляемые сервисы:",
    "add_service.required_components": "Необходимые компоненты (будут добавлены автоматически):",
    "add_service.already_have_components": (
        "Необходимые компоненты уже есть: {components}"
    ),
    "add_service.confirm": "Добавить эти сервисы?",
    "add_service.adding_component": "Добавление компонента: {component}...",
    "add_service.failed_component": "Не удалось добавить компонент {component}: {error}",
    "add_service.added_files": "Добавлено файлов: {count}",
    "add_service.skipped_files": "Пропущено файлов: {count}",
    "add_service.preserved_files": "Требуется ручная проверка общих файлов: {count} (см. сообщения выше)",
    "add_service.adding_service": "Добавление сервиса: {service}...",
    "add_service.failed_service": "Не удалось добавить сервис {service}: {error}",
    "add_service.resolve_failed": "Не удалось разрешить зависимости сервиса: {error}",
    "add_service.bootstrap_alembic": "Инициализация инфраструктуры alembic...",
    "add_service.created_file": "Создано: {file}",
    "add_service.generated_migration": "Создана миграция: {name}",
    "add_service.applying_migrations": "Применение миграций БД...",
    "add_service.migration_failed": (
        "Внимание: автомиграция не удалась. Выполните «make migrate» вручную."
    ),
    "add_service.success": "Сервисы добавлены!",
    "add_service.failed": "Не удалось добавить сервисы: {error}",
    "add_service.auth_setup": "Настройка Auth:",
    "add_service.auth_create_users": "   1. Создайте тестовых пользователей: {cmd}",
    "add_service.auth_view_routes": "   2. Просмотр маршрутов аутентификации: {url}",
    "add_service.ai_setup": "Настройка AI:",
    "add_service.ai_set_provider": (
        "   1. Укажите {env_var} в .env (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": "   2. Укажите API-ключ провайдера ({env_var} и т.д.)",
    "add_service.ai_test_cli": "   3. Проверка через CLI: {cmd}",
    # ── Команда remove-service ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack — Удаление сервисов",
    "remove_service.project": "Проект: {path}",
    "remove_service.error_no_args": (
        "Ошибка: требуется аргумент services (или --interactive)"
    ),
    "remove_service.usage_hint": "Использование: aegis remove-service auth,ai",
    "remove_service.interactive_hint": "Или: aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "Предупреждение: флаг --interactive игнорирует аргументы сервисов"
    ),
    "remove_service.no_selected": "Сервисы для удаления не выбраны",
    "remove_service.not_enabled": "Не включены: {services}",
    "remove_service.nothing_to_remove": "Нечего удалять!",
    "remove_service.validation_failed": "Ошибка валидации сервисов: {error}",
    "remove_service.load_config_failed": (
        "Не удалось загрузить конфигурацию проекта: {error}"
    ),
    "remove_service.services_to_remove": "Удаляемые сервисы:",
    "remove_service.auth_warning": "ВАЖНО: Предупреждение об удалении Auth",
    "remove_service.auth_delete_intro": "Удаление сервиса аутентификации удалит:",
    "remove_service.auth_delete_endpoints": "API-эндпоинты аутентификации",
    "remove_service.auth_delete_models": "Модель пользователя и сервисы аутентификации",
    "remove_service.auth_delete_jwt": "Код обработки JWT-токенов",
    "remove_service.auth_db_note": (
        "Примечание: таблицы БД и миграции alembic НЕ удаляются."
    ),
    "remove_service.warning_delete": (
        "ВНИМАНИЕ: файлы сервисов будут УДАЛЕНЫ из проекта!"
    ),
    "remove_service.confirm": "Удалить эти сервисы?",
    "remove_service.removing": "Удаление сервиса: {service}...",
    "remove_service.failed_service": "Не удалось удалить сервис {service}: {error}",
    "remove_service.removed_files": "Удалено файлов: {count}",
    "remove_service.success": "Сервисы удалены!",
    "remove_service.failed": "Не удалось удалить сервисы: {error}",
    "remove_service.deps_not_removed": (
        "Примечание: зависимости сервисов (БД и т.д.) НЕ удалены."
    ),
    "remove_service.deps_remove_hint": (
        "Используйте «aegis remove <компонент>» для отдельного удаления компонентов."
    ),
    # ── Команда version ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Команда components ─────────────────────────────────────────────
    "components.core_title": "БАЗОВЫЕ КОМПОНЕНТЫ",
    "components.backend_desc": (
        "  backend      — FastAPI backend-сервер (всегда включён)"
    ),
    "components.frontend_desc": ("  frontend     — Flet интерфейс (всегда включён)"),
    "components.infra_title": "КОМПОНЕНТЫ ИНФРАСТРУКТУРЫ",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "Требуется: {deps}",
    "components.recommends": "Рекомендуется: {deps}",
    "components.usage_hint": (
        "Используйте «aegis init PROJECT_NAME --components redis,worker» для выбора компонентов"
    ),
    # ── Команда services ───────────────────────────────────────────────
    "services.title": "ДОСТУПНЫЕ СЕРВИСЫ",
    "services.type_auth": "Сервисы аутентификации",
    "services.type_payment": "Платёжные сервисы",
    "services.type_ai": "Сервисы AI и машинного обучения",
    "services.type_notification": "Сервисы уведомлений",
    "services.type_analytics": "Сервисы аналитики",
    "services.type_storage": "Сервисы хранения",
    "services.type_content": "Контент-сервисы",
    "services.type_finance": "Финансовые сервисы",
    "services.requires_components": "Требуемые компоненты: {deps}",
    "services.recommends_components": "Рекомендуемые компоненты: {deps}",
    "services.requires_services": "Требуемые сервисы: {deps}",
    "services.none_available": "  Сервисы пока недоступны.",
    "services.usage_hint": (
        "Используйте «aegis init PROJECT_NAME --services auth» для добавления сервисов"
    ),
    # ── Команда update ─────────────────────────────────────────────────
    "update.title": "Aegis Stack — Обновление шаблона",
    "update.not_copier": "Проект в {path} не создан через Copier.",
    "update.copier_only": (
        "Команда «aegis update» работает только с проектами, созданными через Copier."
    ),
    "update.need_regen": "Проекты, созданные до v0.2.0, необходимо пересоздать.",
    "update.project": "Проект: {path}",
    "update.commit_or_stash": (
        "Закоммитьте или спрячьте (stash) изменения перед «aegis update»."
    ),
    "update.clean_required": (
        "Copier требует чистое дерево git для безопасного слияния."
    ),
    "update.git_clean": "Дерево git чистое",
    "update.dirty_tree": "В дереве git есть незакоммиченные изменения",
    "update.changelog_breaking": "Критические изменения:",
    "update.changelog_features": "Новые возможности:",
    "update.changelog_fixes": "Исправления:",
    "update.changelog_other": "Прочие изменения:",
    "update.current_commit": "   Текущий: {commit}...",
    "update.target_commit": "   Целевой:  {commit}...",
    "update.unknown_version": "Внимание: не удаётся определить версию шаблона",
    "update.untagged_commit": ("Проект мог быть создан из коммита без тега"),
    "update.custom_template": "Пользовательский шаблон ({source}): {path}",
    "update.version_info": "Информация о версии:",
    "update.current_cli": "   Текущий CLI:      {version}",
    "update.current_template": "   Текущий шаблон:   {version}",
    "update.current_template_commit": "   Текущий шаблон:   {commit}... (коммит)",
    "update.current_template_unknown": "   Текущий шаблон:   неизвестно",
    "update.target_template": "   Целевой шаблон:   {version}",
    "update.already_at_version": "Проект уже на запрашиваемой версии",
    "update.already_at_commit": "Проект уже на целевом коммите",
    "update.ahead_of_target": ("Проект новее целевой версии шаблона"),
    "update.ahead_of_target_hint": (
        "Обновлять нечего. Используйте --to-version, чтобы выбрать конкретную версию."
    ),
    "update.downgrade_blocked": "Понижение версии не поддерживается",
    "update.downgrade_reason": (
        "Copier не поддерживает откат к более ранним версиям шаблона."
    ),
    "update.changelog": "Журнал изменений:",
    "update.dry_run": "ПРОБНЫЙ ЗАПУСК — изменения не будут применены",
    "update.dry_run_hint": "Для применения обновления выполните:",
    "update.confirm": "Применить обновление?",
    "update.cancelled": "Обновление отменено",
    "update.creating_backup": "Создание точки восстановления...",
    "update.backup_created": "   Бэкап создан: {tag}",
    "update.backup_failed": "Не удалось создать точку восстановления",
    "update.updating": "Обновление проекта...",
    "update.updating_to": "Обновление до версии шаблона {version}",
    "update.moved_files": "   Перемещено {count} новых файлов из вложенного каталога",
    "update.synced_files": "   Синхронизировано {count} изменений шаблона",
    "update.merge_conflicts": (
        "   {count} файл(ов) с конфликтами слияния (ищите <<<<<<< для разрешения):"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "Выполнение пост-генерационных задач...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": "   __aegis_version__ обновлён до {version}",
    "update.success": "Обновление завершено!",
    "update.partial_success": (
        "Обновление завершено, но некоторые пост-генерационные задачи не выполнились"
    ),
    "update.partial_detail": "   Некоторые задачи не выполнились. См. детали выше.",
    "update.next_steps": "Следующие шаги:",
    "update.next_review": "   1. Просмотрите изменения: git diff",
    "update.next_conflicts": "   2. Проверьте конфликты (файлы *.rej)",
    "update.next_test": "   3. Запустите тесты: make check",
    "update.next_commit": "   4. Закоммитьте изменения: git add . && git commit",
    "update.failed": "Обновление не удалось: {error}",
    "update.rollback_prompt": "Откатить до предыдущего состояния?",
    "update.manual_rollback": "Ручной откат: git reset --hard {tag}",
    "update.troubleshooting": "Устранение неполадок:",
    "update.troubleshoot_clean": "   - Убедитесь, что дерево git чистое",
    "update.troubleshoot_version": "   - Проверьте существование версии/коммита",
    "update.troubleshoot_docs": "   - Обратитесь к документации Copier по проблемам обновления",
    # ── Команда ingress ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack — Включение Ingress TLS",
    "ingress.project": "Проект: {path}",
    "ingress.not_found": "Компонент ingress не найден. Добавляется...",
    "ingress.add_confirm": "Добавить компонент ingress?",
    "ingress.add_failed": "Не удалось добавить компонент ingress: {error}",
    "ingress.added": "Компонент ingress добавлен.",
    "ingress.tls_already": "TLS уже включён в этом проекте.",
    "ingress.domain_label": "   Домен: {domain}",
    "ingress.acme_email": "   ACME email: {email}",
    "ingress.domain_prompt": (
        "Доменное имя (напр., example.com, или пусто для IP-маршрутизации)"
    ),
    "ingress.email_reuse": "Используется существующий email для ACME: {email}",
    "ingress.email_prompt": "Email для уведомлений Let's Encrypt",
    "ingress.email_required": (
        "Ошибка: --email обязателен для TLS (нужен для Let's Encrypt)"
    ),
    "ingress.tls_config": "Конфигурация TLS:",
    "ingress.domain_none": "   Домен: (нет — маршрутизация по IP/PathPrefix)",
    "ingress.tls_confirm": "Включить TLS с данной конфигурацией?",
    "ingress.enabling": "Включение TLS...",
    "ingress.updated_file": "   Обновлено: {file}",
    "ingress.created_file": "   Создано: {file}",
    "ingress.success": "TLS включён!",
    "ingress.available_at": "   Приложение будет доступно по: https://{domain}",
    "ingress.https_configured": "   HTTPS настроен с Let's Encrypt",
    "ingress.next_steps": "Следующие шаги:",
    "ingress.next_deploy": "   1. Разверните: aegis deploy",
    "ingress.next_ports": "   2. Убедитесь, что порты 80 и 443 открыты на сервере",
    "ingress.next_dns": (
        "   3. Настройте DNS A-запись для {domain} на IP вашего сервера"
    ),
    "ingress.next_certs": "   Сертификаты будут выпущены автоматически при первом запросе",
    # ── Команды deploy ─────────────────────────────────────────────────
    "deploy.no_config": (
        "Конфигурация деплоя не найдена. Выполните «aegis deploy-init» сначала."
    ),
    "deploy.init_saved": "Конфигурация деплоя сохранена в {file}",
    "deploy.init_host": "   Хост: {host}",
    "deploy.init_user": "   Пользователь: {user}",
    "deploy.init_path": "   Путь: {path}",
    "deploy.init_docker_context": "   Docker Context: {context}",
    "deploy.prompt_host": "IP-адрес или имя сервера",
    "deploy.init_gitignore": (
        "Примечание: добавьте .aegis/ в .gitignore, чтобы не коммитить конфиг деплоя"
    ),
    "deploy.setup_title": "Настройка сервера {target}...",
    "deploy.checking_ssh": "Проверка SSH-подключения...",
    "deploy.adding_host_key": "Добавление сервера в known_hosts...",
    "deploy.ssh_keyscan_failed": "Не удалось получить SSH-ключ хоста: {error}",
    "deploy.ssh_failed": "SSH-подключение не удалось: {error}",
    "deploy.copying_script": "Копирование скрипта настройки на сервер...",
    "deploy.copy_failed": "Не удалось скопировать скрипт настройки",
    "deploy.running_setup": "Запуск настройки сервера (может занять несколько минут)...",
    "deploy.setup_failed": "Настройка сервера не удалась",
    "deploy.setup_script_missing": "Скрипт настройки не найден: {path}",
    "deploy.setup_script_hint": ("Убедитесь, что проект создан с компонентом ingress."),
    "deploy.setup_complete": "Настройка сервера завершена!",
    "deploy.setup_verify": "Проверка установки:",
    "deploy.setup_verify_docker": "  Docker: {version}",
    "deploy.setup_verify_compose": "  Docker Compose: {version}",
    "deploy.setup_verify_uv": "  uv: {version}",
    "deploy.setup_verify_app_dir": "  Каталог приложения: {path}",
    "deploy.setup_next": "Далее: выполните «aegis deploy» для развёртывания приложения",
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
    "deploy.deploying": "Развёртывание на {host}...",
    "deploy.creating_backup": "Создание бэкапа {timestamp}...",
    "deploy.backup_failed": "Не удалось создать бэкап: {error}",
    "deploy.backup_db": "Резервное копирование БД PostgreSQL...",
    "deploy.backup_db_neon": "Базой данных управляет Neon (ветки / восстановление на момент времени); локальный бэкап пропускается",
    "deploy.backup_db_failed": ("Внимание: бэкап БД не удался, продолжение без него"),
    "deploy.backup_created": "Бэкап создан: {timestamp}",
    "deploy.backup_pruned": "Удалён старый бэкап: {name}",
    "deploy.no_existing": "Предыдущее развёртывание не найдено, бэкап пропущен",
    "deploy.syncing": "Синхронизация файлов на сервер...",
    "deploy.mkdir_failed": "Не удалось создать каталог «{path}» на сервере",
    "deploy.sync_failed": "Не удалось синхронизировать файлы",
    "deploy.copying_env": "Копирование {file} на сервер как .env...",
    "deploy.env_copy_failed": "Не удалось скопировать файл .env",
    "deploy.stopping": "Остановка сервисов...",
    "deploy.building": "Сборка и запуск сервисов на сервере...",
    "deploy.start_failed": "Не удалось запустить сервисы",
    "deploy.auto_rollback": "Автоматический откат к предыдущей версии...",
    "deploy.health_waiting": "Ожидание стабилизации контейнеров...",
    "deploy.health_attempt": "Проверка состояния {n}/{total}...",
    "deploy.health_passed": "Проверка состояния пройдена",
    "deploy.health_retry": "Проверка не пройдена, повтор через {interval}с...",
    "deploy.health_all_failed": "Все попытки проверки состояния неудачны",
    "deploy.rolled_back": "Откат к бэкапу {timestamp} выполнен",
    "deploy.rollback_failed": "Откат не удался! Требуется ручное вмешательство.",
    "deploy.health_failed_hint": (
        "Деплой завершён, но проверка состояния не пройдена. Проверьте логи: aegis deploy-logs"
    ),
    "deploy.complete": "Развёртывание завершено!",
    "deploy.rolling_starting": "Плавное развёртывание на {host}...",
    "deploy.rolling_building": "Сборка образа веб-сервера...",
    "deploy.rolling_pausing": "Приостановка очереди воркеров...",
    "deploy.rolling_pause_failed": (
        "Не удалось установить флаг паузы; воркеры могут получить "
        "SIGTERM посреди задачи."
    ),
    "deploy.rolling_draining": (
        "Ожидание до {seconds}с для завершения работы воркеров..."
    ),
    "deploy.rolling_drain_timeout": (
        "Воркеры не завершились вовремя. Флаг паузы очищен; прерываем."
    ),
    "deploy.rolling_recreating": "Пересоздание: {services}",
    "deploy.rolling_webserver": (
        "Плавный перезапуск веб-сервера (ожидание готовности до {seconds}с)..."
    ),
    "deploy.rolling_rollout_failed": (
        "docker rollout завершился ошибкой. Установлен ли плагин в "
        "~/.docker/cli-plugins/ на хосте развёртывания?"
    ),
    "deploy.rolling_complete": "Плавное развёртывание завершено!",
    "deploy.app_running": "   Приложение работает по: http://{host}",
    "deploy.overseer": "   Панель Overseer: http://{host}/dashboard/",
    "deploy.view_logs": "   Просмотр логов: aegis deploy-logs",
    "deploy.check_status": "   Проверка статуса: aegis deploy-status",
    "deploy.backup_complete": "Бэкап завершён!",
    "deploy.creating_backup_on": "Создание бэкапа на {host}...",
    "deploy.no_backups": "Бэкапы не найдены.",
    "deploy.backups_header": "Бэкапы на {host} (всего {count}):",
    "deploy.col_timestamp": "Время",
    "deploy.col_size": "Размер",
    "deploy.col_database": "БД",
    "deploy.rollback_hint": ("Откат: aegis deploy-rollback --backup <timestamp>"),
    "deploy.no_backups_available": "Бэкапы отсутствуют.",
    "deploy.rolling_back": "Откат к бэкапу {backup} на {host}...",
    "deploy.rollback_not_found": "Бэкап не найден: {timestamp}",
    "deploy.rollback_stopping": "Остановка сервисов...",
    "deploy.rollback_restoring": "Восстановление файлов из бэкапа {timestamp}...",
    "deploy.rollback_restore_failed": "Не удалось восстановить файлы: {error}",
    "deploy.rollback_db": "Восстановление БД...",
    "deploy.rollback_db_neon": "Восстановлением базы данных управляет Neon (ветки / восстановление на момент времени); локальное восстановление пропускается",
    "deploy.rollback_pg_wait": "Ожидание готовности PostgreSQL...",
    "deploy.rollback_pg_timeout": (
        "PostgreSQL не готов, попытка восстановления в любом случае"
    ),
    "deploy.rollback_db_failed": "Внимание: восстановление БД не удалось",
    "deploy.rollback_starting": "Запуск сервисов...",
    "deploy.rollback_start_failed": "Не удалось запустить сервисы после отката",
    "deploy.rollback_complete": "Откат завершён!",
    "deploy.rollback_failed_final": "Откат не удался!",
    "deploy.status_header": "Статус сервисов на {host}:",
    "deploy.stop_stopping": "Остановка сервисов...",
    "deploy.stop_success": "Сервисы остановлены",
    "deploy.stop_failed": "Не удалось остановить сервисы",
    "deploy.restart_restarting": "Перезапуск сервисов...",
    "deploy.restart_success": "Сервисы перезапущены",
    "deploy.restart_failed": "Не удалось перезапустить сервисы",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": "Путь к проекту Aegis Stack (по умолчанию: текущий каталог)",
    "common.help_project_path": "Путь к проекту (по умолчанию: текущий каталог)",
    "common.help_yes": "Пропустить запрос подтверждения",
    "common.help_yes_plural": "Пропустить все запросы подтверждения",
    "common.help_interactive_components": "Выбрать компоненты интерактивно",
    "common.help_interactive_services": "Выбрать сервисы интерактивно",
    "common.help_force": "Игнорировать предупреждения о несовместимости версий",
    # ── init CLI help ──────────────────────────────────────────────────
    "blueprints.title": "AVAILABLE BLUEPRINTS",
    "blueprints.none_available": "No blueprints available.",
    "blueprints.includes": "Includes: {names}",
    "blueprints.usage_hint": "Start a project from one:",
    "init.help_opt_blueprint": (
        "Start from a named blueprint (a preset component/service selection)"
    ),
    "init.unknown_blueprint": "Unknown blueprint: {name}. Available: {available}",
    "init.help_arg_name": "Имя нового проекта Aegis Stack",
    "init.help_opt_components": "Список компонентов через запятую (redis, worker, scheduler, database)",
    "init.help_opt_python": "Версия Python для генерируемого проекта (3.11, 3.12, 3.13 или 3.14)",
    "init.help_opt_force": "Перезаписать существующий каталог, если он есть",
    "init.help_opt_directory": "Каталог, в котором будет создан проект (по умолчанию: текущий каталог)",
    "init.help_opt_template_version": "Сгенерировать из указанной версии шаблона (тег, коммит или ветка)",
    "init.help_opt_no_llm_sync": "Пропустить синхронизацию каталога LLM после генерации (только для сервиса AI)",
    "init.help_opt_dev": "Dev-режим: читать шаблоны из рабочего дерева (включая незакоммиченные изменения)",
    "init.help_opt_services": "Сервисы: {services}. Опции AI: ai[framework,backend,providers], где framework={frameworks}, backend={backends}, providers={providers}",
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": "Список добавляемых компонентов через запятую (scheduler, worker, database)",
    "add.help_opt_scheduler_backend": "Бэкенд планировщика: «memory» (по умолчанию) или «sqlite» (включает персистентность)",
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "Обновить до конкретной версии (по умолчанию: последняя)",
    "update.help_opt_dry_run": "Предпросмотр изменений без их применения",
    "update.help_opt_template_path": "Использовать произвольный путь к шаблону вместо установленной версии",
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": "Список удаляемых компонентов через запятую (scheduler, worker, database)",
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": "Список добавляемых сервисов через запятую (auth, ai)",
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": "Список удаляемых сервисов через запятую (auth, ai, comms)",
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": "Доменное имя для TLS-сертификата (например, example.com)",
    "ingress.help_opt_email": "Email для уведомлений Let's Encrypt о сертификатах",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "IP-адрес или имя хоста сервера",
    "deploy.help_opt_user": "SSH-пользователь для деплоя",
    "deploy.help_opt_path": "Путь деплоя на сервере",
    "deploy.help_opt_public_key": "Путь к публичному ключу, который будет добавлен в authorized_keys пользователя деплоя (идемпотентно). Позволяет не запускать ssh-copy-id вручную перед деплоем.",
    "deploy.help_opt_build": "Собрать образы перед деплоем",
    "deploy.help_opt_backup": "Создать бэкап перед деплоем",
    "deploy.help_opt_health": "Выполнить проверку работоспособности после деплоя",
    "deploy.help_opt_rolling": (
        "Развёртывание только кода без HTTP-простоя. Перекатывает "
        "веб-сервер через docker-rollout и приостанавливает очередь "
        "воркеров, чтобы выполняющиеся задачи завершились корректно. "
        "Пропускает миграции БД."
    ),
    "deploy.help_opt_drain_timeout": (
        "Секунд ожидания завершения работы воркеров после приостановки "
        "очереди при плавном развёртывании (по умолчанию: 90)."
    ),
    "deploy.help_opt_rollout_timeout": (
        "Сколько секунд docker-rollout ждёт готовности нового веб-сервера "
        "при плавном развёртывании. Задавайте по бюджету HEALTHCHECK "
        "контейнера (start_period + retries × interval), а не по "
        "60-секундному таймеру (по умолчанию: 900)."
    ),
    "deploy.help_opt_rollback_backup": "Метка времени бэкапа для отката (по умолчанию: последний)",
    "deploy.help_opt_logs_follow": "Следить за выводом логов в реальном времени",
    "deploy.help_opt_logs_service": "Показать логи только для указанного сервиса",
    "deploy.help_opt_shell_service": "Сервис, к которому подключиться",
    "deploy.help_opt_gh_repo": "Репозиторий GitHub в формате owner/name (по умолчанию: автоопределение из git remote origin)",
    "deploy.help_opt_gh_tags": "Запускать workflow деплоя также при push в теги v*",
    "deploy.help_opt_gh_overwrite": "Перезаписать существующие GitHub Secrets и workflow deploy.yml",
    "deploy.help_opt_dry_run": "Показать планируемые действия без внесения изменений",
    "deploy.help_opt_local_key_path": "Путь, по которому будет сохранён сгенерированный приватный ключ перед очисткой. По умолчанию: без локальной копии (ключ хранится только в GitHub Secrets).",
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "Просмотр установленных плагинов Aegis и поиск в реестре",
    "plugins.cannot_read_answers": "Не удалось прочитать {path}: {error}. Проверки совместимости будут пропущены.",
    "plugins.help_list": "Список установленных плагинов и их совместимость с этим проектом.",
    "plugins.help_opt_list_project_path": "Проект, для которого оценивается совместимость (по умолчанию: текущий каталог, если это проект Aegis).",
    "plugins.help_opt_list_verbose": "Показать столбец с описанием.",
    "plugins.section_in_tree": "Встроенные (официальные)",
    "plugins.section_external": "Внешние плагины",
    "plugins.col_name": "Имя",
    "plugins.col_version": "Версия",
    "plugins.col_kind": "Тип",
    "plugins.col_description": "Описание",
    "plugins.col_status": "Статус",
    "plugins.no_external_installed": "Внешние плагины не установлены. Установить можно через: pip install aegis-plugin-<name>",
    "plugins.help_info": "Подробная информация об одном плагине.",
    "plugins.help_arg_info_name": "Имя плагина (например, «auth», «scraper»)",
    "plugins.help_opt_info_project_path": "Проект, для которого оценивается совместимость.",
    "plugins.not_installed_named": "Плагин с именем «{name}» не установлен.",
    "plugins.available_list": "Доступны: {names}",
    "plugins.label_first_party": "(официальный)",
    "plugins.label_verified": "(проверенный)",
    "plugins.label_unverified": "(сообщество, не проверен)",
    "plugins.label_kind": "Тип:",
    "plugins.label_type": "Подтип:",
    "plugins.label_requires_components": "Нужны комп.:",
    "plugins.label_recommends_components": "Рекомендуются:",
    "plugins.label_requires_services": "Нужны сервисы:",
    "plugins.label_requires_plugins": "Нужны плагины:",
    "plugins.label_conflicts": "Конфликты:",
    "plugins.label_python_deps": "Зависимости Python:",
    "plugins.deps_more": "(ещё {count})",
    "plugins.section_options": "Опции",
    "plugins.option_choices": "значения:",
    "plugins.option_default": "по умолчанию:",
    "plugins.option_auto_requires": "(c auto_requires)",
    "plugins.info_files": "Файлы: {files}   Миграции: {migrations} ({tables} табл.)   CLI: {cli}",
    "plugins.cli_yes": "да",
    "plugins.cli_no": "нет",
    "plugins.section_compat": "Совместимость",
    "plugins.help_update": "Заново сгенерировать шаблоны установленного плагина по текущей версии, установленной через pip.",
    "plugins.help_arg_update_name": "Плагин для обновления. Обязателен, если не указан --all.",
    "plugins.help_opt_update_all": "Обновить все плагины, перечисленные в _plugins этого проекта.",
    "plugins.help_opt_update_force": "Применить обновление, даже если ограничение aegis_version новой версии плагина исключает текущий CLI.",
    "plugins.update_need_target": "Укажите имя плагина или используйте --all.",
    "plugins.update_either_not_both": "Передайте либо имя плагина, либо --all, но не одновременно.",
    "plugins.update_no_plugins_installed": "В этом проекте нет установленных плагинов.",
    "plugins.update_not_in_project": "Плагин «{name}» не установлен в этом проекте.",
    "plugins.update_use_list_hint": "Посмотреть доступные плагины: `aegis plugins list`, установить: `aegis add <name>`.",
    "plugins.update_not_pip_installed": "Плагин «{name}» присутствует в _plugins проекта, но не установлен через pip; сначала выполните `pip install aegis-plugin-{name}`.",
    "plugins.update_already_at": "{name} (уже {version})",
    "plugins.update_forcing": "Обновление выполняется, несмотря на несовместимость версий: {error}",
    "plugins.update_progress": "Обновление плагина: {name} ({old} → {new})",
    "plugins.update_confirm_apply": "Применить обновление к «{name}»?",
    "plugins.update_skipped_by_user": "{name} (пропущено пользователем)",
    "plugins.update_legacy_strings": "Пропуск устаревших строковых записей _plugins: {entries}. Добавьте их заново через `aegis add <name>`, чтобы перейти на текущий формат dict.",
    "plugins.update_summary_updated": "Обновлено: {count}",
    "plugins.update_summary_skipped": "Пропущено: {count}",
    "plugins.update_summary_failed": "Ошибок: {count}",
    "plugins.help_create": "Сгенерировать каркас нового Python-пакета aegis-plugin-<name>.",
    "plugins.help_arg_create_name": "Имя плагина (нижний регистр, без дефисов). Используется как имя Python-пакета aegis_plugin_<name> и имя установки aegis-plugin-<name>.",
    "plugins.help_opt_create_target": "Родительский каталог, в котором будет создан каркас плагина.",
    "plugins.help_opt_create_author": "Строка автора для pyproject.toml и README.",
    "plugins.help_opt_create_description": "Однострочное описание плагина.",
    "plugins.create_target_missing": "Целевой каталог не существует: {target}",
    "plugins.create_already_exists": "Каталог уже существует: {output}",
    "plugins.create_pick_different": "Выберите другое имя или удалите существующий каталог.",
    "plugins.create_starting": "Создание плагина: {name}",
    "plugins.create_label_target": "Назначение:",
    "plugins.create_label_author": "Автор:",
    "plugins.create_label_description": "Описание:",
    "plugins.create_default_marker": "(по умолчанию)",
    "plugins.create_confirm": "Создать каркас?",
    "plugins.create_cancelled": "Отменено.",
    "plugins.create_success": "Создано {count} файлов в {output}",
    "plugins.create_next_steps_header": "Следующие шаги:",
    "plugins.create_next_steps_confirm_comment": "проверить, что плагин обнаружен",
    "plugins.create_next_steps_edit_comment": "отредактировать src/aegis_plugin_<name>/plugin.py и добавить связку",
    "plugins.help_search": "Поиск в официальном реестре плагинов.",
    "plugins.help_arg_search_keyword": "Необязательное ключевое слово для поиска",
    "plugins.search_not_available": "Реестр плагинов пока недоступен.",
    "plugins.search_install_hint": "Пока что: pip install aegis-plugin-<name>, затем aegis plugins list.",
    "plugins.search_future_keyword": "Когда реестр будет запущен, эта команда будет искать «{keyword}».",
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "Готовые к продакшену приложения на Python с первого дня.",
    "guided.welcome.body": "Эта пошаговая настройка проводит по каждому компоненту с кратким пояснением, чтобы вы решили, что нужно вашему проекту. Выберите только то, что нужно сейчас; остальное можно добавить позже с помощью 'aegis add'.",
    "guided.corestack.title": "ВКЛЮЧЕНО В КАЖДЫЙ ПРОЕКТ",
    "guided.corestack.body": "Каждый проект Aegis начинается с этих двух — связанных вместе и готовых к запуску.",
    "guided.sidebar.components": "КОМПОНЕНТЫ",
    "guided.sidebar.services": "СЕРВИСЫ",
    "guided.prompt.worker_backend": "Выберите бэкенд воркера",
    "guided.prompt.scheduler_backend": "Постоянство планировщика: сохранять историю задач между перезапусками?",
    "guided.prompt.database_engine": "Движок базы данных для {context}",
    "guided.prompt.postgres_provider": "Хост PostgreSQL для {context}",
    "guided.prompt.auth_level": "Уровень аутентификации",
    "guided.prompt.ai_framework": "AI-фреймворк",
    "guided.prompt.ai_providers": "AI-провайдеры: выберите любые для подключения",
    "guided.prompt.ai_storage": "Хранение AI-диалогов",
    "guided.prompt.ai_rag": "Добавить RAG: чат на основе ваших документов и кода?",
    "guided.prompt.ai_voice": "Добавить голос: синтез и распознавание речи?",
    "guided.note.one_datastore": "Одно хранилище на проект: выбранный здесь движок задаёт базу данных проекта, общую для всего, что хранит данные.",
    "guided.note.one_database_host": "Одна база данных на проект: этот хост обслуживает всё, что хранит данные.",
    "guided.multi.hint": "Отметьте сколько угодно, затем выберите «Продолжить».",
    "guided.choice.add": "Добавить",
    "guided.choice.skip": "Пропустить",
    "guided.screen.add_question": "Добавить {name}?",
    "guided.screen.too_small": "Терминал слишком мал. Увеличьте хотя бы до {w}x{h}.",
    "guided.review.title": "ВАША КОНФИГУРАЦИЯ",
    "guided.review.files_pane": "ФАЙЛЫ КОМПОНЕНТОВ",
    "guided.review.deps_pane": "ЗАВИСИМОСТИ",
    "guided.review.counts": "файлов компонентов: {files} · зависимостей: {deps}",
    "guided.building.title": "Сборка {name} …",
    "guided.building.preparing": "Подготовка …",
    "guided.building.note": "Это может занять минуту-другую; основную работу выполняет uv.",
    "guided.hint.building": "сборка …",
    "guided.done.ready": "{name} готов",
    "guided.done.body": "Проект создан, зависимости установлены.",
    "guided.done.next_steps": "ДАЛЬНЕЙШИЕ ШАГИ",
    "guided.done.project_structure": "СТРУКТУРА ПРОЕКТА",
    "guided.done.recreate": "ПЕРЕСОЗДАТЬ ЭТОТ СТЕК В ЛЮБОЕ ВРЕМЯ",
    "guided.done.copy_note": "Нажмите c, чтобы скопировать; полная команда также будет показана ниже после завершения.",
    "guided.done.copied": "Скопировано в буфер обмена ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "Продолжить",
    "guided.header.label": "пошаговая настройка",
    "guided.hint.move": "перемещение",
    "guided.hint.select": "выбрать",
    "guided.hint.toggle": "переключить",
    "guided.hint.back": "назад",
    "guided.hint.begin": "начать",
    "guided.hint.build": "создать",
    "guided.hint.next": "далее",
    "guided.hint.finish": "готово",
    "guided.hint.quit": "выход",
    "guided.hint.services": "перейти к сервисам",
    "guided.hint.copy": "копировать команду",
    "guided.hint.deps": "зависимости",
    "guided.hint.files": "файлы",
    "guided.review.core": "Ядро:",
    "guided.review.infrastructure": "Инфраструктура:",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "Сервисы:",
    "guided.review.auto": "авто",
    "guided.review.build": "Создать {name}",
    "guided.review.more": "… ещё {n}",
    "guided.screen.requires": "Требует:",
    "guided.screen.added_automatically": "(добавляется автоматически)",
    "guided.screen.pairs": "Хорошо сочетается с:",
    "guided.screen.docs": "Документация:",
    "component.backend.long": "Приложение FastAPI, обслуживающее ваш API, асинхронное с самого начала: типизированные маршруты, автоматическая документация OpenAPI, проверки работоспособности и набор тестов, уже покрывающий всё это.",
    "component.frontend.long": "Панель управления Flet, показывающая работоспособность системы в реальном времени и состояние каждого выбранного здесь компонента, готовая расшириться до ваших собственных представлений. Python от начала до конца, без сборочной цепочки JavaScript.",
    "component.worker.long": "Фоновая обработка задач с выбором бэкенда: arq (по умолчанию), Dramatiq или TaskIQ. Выносите медленные операции — письма, экспорт, вызовы сторонних API — чтобы запросы оставались быстрыми. Работает на Redis, который добавляется автоматически.",
    "component.scheduler.long": "Планирование фоновых задач и cron-задания на базе APScheduler. Выполняйте периодическую работу — очистку, отчёты, проверки — по расписанию. Необязательное сохранение в базе данных хранит историю задач и переживает перезапуски.",
    "component.database.long": "Постоянное хранилище с ORM SQLModel, миграциями Alembic и пулом соединений. SQLite даёт файловую базу без настройки для разработки; PostgreSQL — выбор для продакшена. На этом строится большинство сервисов.",
    "component.redis.long": "Хранилище данных в памяти, используемое как кэш и брокер сообщений. Обеспечивает работу очередей фоновых задач и pub/sub-обмена между сервисами и даёт обработчикам запросов быстрый общий кэш.",
    "component.ingress.long": "Обратный прокси и маршрутизация трафика с Traefik: автоматическое обнаружение сервисов, защита админ-эндпоинтов и необязательный TLS через Let's Encrypt. Точка входа для развёртываний.",
    "component.observability.long": "Распределённая трассировка, метрики и корреляция логов с Pydantic Logfire. Автоматически инструментирует ваше приложение и подстраивается под включённые компоненты, чтобы вы видели, что на самом деле происходит в продакшене.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "Полное управление пользователями с JWT-аутентификацией, сессионными cookie и ротацией refresh-токенов. Три уровня: базовый email/пароль, роли и права RBAC или мультитенантные организации. Включает регистрацию, вход и вкладку админ-панели.",
    "service.ai.long": "Полноценная AI-платформа: чат с несколькими провайдерами, каталог LLM примерно из 2000 моделей, учёт затрат с аналитикой использования, необязательный RAG для диалогов с учётом кодовой базы и необязательный голос (TTS/STT). В качестве фреймворка выберите Pydantic AI или LangChain.",
    "service.comms.long": "Email, SMS и голосовые вызовы через ведущих провайдеров: Resend для почты, Twilio для SMS и голоса. У обоих есть бесплатные тарифы, так что можно начать без кредитной карты.",
    "service.insights.long": "Автоматическое отслеживание распространения вашего проекта в GitHub, PyPI, Plausible Analytics и Reddit. Собирает по расписанию, хранит историю и визуализирует рост на панели.",
    "service.payment.long": "Обработка платежей через Stripe: сессии оплаты, подписки, вебхуки и возвраты. Тестовый режим Stripe не требует кредитной карты, так что можно построить весь процесс до запуска.",
    "service.blog.long": "Встроенная публикация в Markdown с хранением постов в базе данных, тегами, черновиками и редактором в панели. Импорт и экспорт постов в виде обычного Markdown с frontmatter.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "В памяти",
    "guided.choice.scheduler.memory": "Без сохранения. Задачи сбрасываются при перезапуске — пропустите, если не уверены.",
    "guided.choice.scheduler.sqlite": "Хранить историю задач в файловой базе данных.",
    "guided.choice.scheduler.postgres": "Хранить историю задач, уровень продакшена.",
    "guided.choice.worker.arq": "Простой, хорошо протестированный асинхронный воркер с минимальной настройкой. Лучше всего для I/O-задач. По умолчанию.",
    "guided.choice.worker.dramatiq": "Многопроцессная модель акторов. Лучше всего для CPU-задач, выигрывающих от нескольких процессов ОС.",
    "guided.choice.worker.taskiq": "Асинхронный по природе, с брокерами на каждую очередь и транспортом Redis Streams с подтверждениями.",
    "guided.choice.db.sqlite": "Файловая база данных без настройки. Отлично для разработки.",
    "guided.choice.db.postgres": "Уровень продакшена, пул соединений.",
    "guided.choice.db_provider.container": "Локальный контейнер postgres:16, dev и prod.",
    "guided.choice.db_provider.neon": (
        "Бессерверный Postgres: облако для prod, локальный контейнер в dev."
    ),
    "guided.choice.auth.basic": "Email и пароль с JWT-сессиями.",
    "guided.choice.auth.rbac": "Добавляет роли и права.",
    "guided.choice.auth.org": "Мультитенантные организации.",
    "guided.choice.framework.pydantic_ai": "Типизированный и лёгкий. По умолчанию.",
    "guided.choice.framework.langchain": "Большая экосистема, множество интеграций.",
    "guided.choice.storage.memory": "Без истории, ничего настраивать не нужно.",
    "guided.choice.storage.sqlite": "Постоянная история чата в файловой базе данных.",
    "guided.choice.storage.postgres": "Постоянное хранение уровня продакшена.",
    "guided.choice.provider.public.desc": "Бесплатный публичный эндпоинт",
    "guided.choice.provider.public.pricing": "Бесплатно, без API-ключа",
    "guided.choice.provider.openai.desc": "Модели GPT",
    "guided.choice.provider.openai.pricing": "Платно",
    "guided.choice.provider.anthropic.desc": "Модели Claude",
    "guided.choice.provider.anthropic.pricing": "Платно",
    "guided.choice.provider.google.desc": "Модели Gemini",
    "guided.choice.provider.google.pricing": "Бесплатный тариф (только Flash)",
    "guided.choice.provider.groq.desc": "Быстрый инференс",
    "guided.choice.provider.groq.pricing": "Бесплатный тариф",
    "guided.choice.provider.mistral.desc": "Открытые модели",
    "guided.choice.provider.mistral.pricing": "В основном платно",
    "guided.choice.provider.cohere.desc": "Фокус на enterprise",
    "guided.choice.provider.cohere.pricing": "Ограниченно бесплатно",
    "guided.choice.provider.ollama.desc": "Локальный инференс",
    "guided.choice.provider.ollama.pricing": "Бесплатно (локально)",
    "build.step.render": "Создание файлов проекта",
    "build.step.deps": "Установка зависимостей",
    "build.step.env": "Настройка окружения",
    "build.step.migrate": "Применение миграций",
    "build.step.llm": "Синхронизация каталога LLM",
    "build.step.format": "Форматирование кода",
}
