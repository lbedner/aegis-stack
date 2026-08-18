"""German locale — Deutsche Nachrichtendefinitionen."""

MESSAGES: dict[str, str] = {
    # ── Validation ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "Ungültiger Projektname. Nur Buchstaben, Zahlen, Bindestriche "
        "und Unterstriche erlaubt."
    ),
    "validation.reserved_name": "'{name}' ist ein reservierter Name.",
    "validation.name_too_long": ("Projektname zu lang. Maximal 50 Zeichen erlaubt."),
    "validation.invalid_python": (
        "Ungültige Python-Version '{version}'. Muss eine von: {supported} sein"
    ),
    "validation.unknown_service": "Unbekannter Service: {name}",
    "validation.unknown_services": "Unbekannte Services: {names}",
    "validation.unknown_component": "Unbekannte Komponente: {name}",
    # ── Init command ───────────────────────────────────────────────────
    "init.title": "Aegis Stack Projektinitialisierung",
    "init.location": "Speicherort:",
    "init.template_version": "Template-Version:",
    "init.dir_exists": "Verzeichnis '{path}' existiert bereits",
    "init.dir_exists_hint": "Nutze --force zum Überschreiben oder wähle einen anderen Namen",
    "init.overwriting": "Überschreibe vorhandenes Verzeichnis: {path}",
    "init.services_require": "Services benötigen Komponenten: {components}",
    "init.compat_errors": "Service-Komponenten-Kompatibilitätsfehler:",
    "init.suggestion_add": (
        "Vorschlag: Fehlende Komponenten hinzufügen --components {components}"
    ),
    "init.suggestion_remove": (
        "Oder --components weglassen, damit Services Abhängigkeiten automatisch hinzufügen."
    ),
    "init.suggestion_interactive": (
        "Alternativ den interaktiven Modus nutzen, um Service-Abhängigkeiten automatisch hinzuzufügen."
    ),
    "init.auto_detected_scheduler": (
        "Automatisch erkannt: Scheduler mit {backend}-Persistenz"
    ),
    "init.auto_added_deps": "Automatisch hinzugefügte Abhängigkeiten: {deps}",
    "init.auto_added_by_services": "Automatisch durch Services hinzugefügt:",
    "init.required_by": "benötigt von {services}",
    "init.config_title": "Projektkonfiguration",
    "init.config_name": "Name:",
    "init.config_core": "Kern:",
    "init.config_infra": "Infrastruktur:",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "Services:",
    "init.component_files": "Komponentendateien:",
    "init.entrypoints": "Einstiegspunkte:",
    "init.worker_queues": "Worker Queues:",
    "init.dependencies": "Zu installierende Abhängigkeiten:",
    "init.confirm_create": "Projekt erstellen?",
    "init.cancelled": "Projekterstellung abgebrochen",
    "init.removing_dir": "Entferne vorhandenes Verzeichnis: {path}",
    "init.creating": "Erstelle Projekt: {name}",
    "init.error": "Fehler beim Erstellen des Projekts: {error}",
    "init.replay_hint": "Erstellen Sie diesen Stack jederzeit neu:",
    # ── Interactive: section headers ───────────────────────────────────
    "interactive.component_selection": "Komponentenauswahl",
    "interactive.service_selection": "Service-Auswahl",
    "interactive.core_included": (
        "Kernkomponenten ({components}) automatisch enthalten"
    ),
    "interactive.infra_header": "Infrastrukturkomponenten:",
    "interactive.services_intro": (
        "Services stellen Geschäftslogik für deine Anwendung bereit."
    ),
    # ── Component descriptions ──────────────────────────────────────────
    "component.backend": "FastAPI Backend-Server",
    "component.frontend": "Flet Frontend-Oberfläche",
    "component.redis": "Redis Cache und Message Broker",
    "component.worker": "Hintergrund-Taskverarbeitung (arq, Dramatiq oder TaskIQ)",
    "component.scheduler": "Infrastruktur für geplante Aufgaben",
    "component.database": "Datenbank mit SQLModel ORM (SQLite oder PostgreSQL)",
    "component.ingress": "Traefik Reverse Proxy und Load Balancer",
    "component.observability": "Logfire Observability, Tracing und Metriken",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Service descriptions ────────────────────────────────────────────
    "service.auth": "Benutzerauthentifizierung und -autorisierung mit JWT-Tokens",
    "service.ai": "AI Chatbot Service mit Multi-Framework-Unterstützung",
    "service.comms": "Kommunikationsservice mit E-Mail, SMS und Sprache",
    "service.blog": "Markdown-Blog mit Entwurfs-, Veröffentlichungs- und Tag-Workflow",
    # ── Interactive: component prompts ─────────────────────────────────
    "interactive.add_prompt": "{description} hinzufügen?",
    "interactive.add_with_redis": "{description} hinzufügen? (fügt Redis automatisch hinzu)",
    "interactive.worker_configured": "Worker mit {backend} Backend konfiguriert",
    # ── Interactive: scheduler ─────────────────────────────────────────
    "interactive.scheduler_persistence": "Scheduler-Persistenz:",
    "interactive.persist_prompt": (
        "Geplante Jobs persistieren? "
        "(Aktiviert Job-Verlauf, Wiederherstellung nach Neustart)"
    ),
    "interactive.scheduler_db_configured": "Scheduler + {engine} Datenbank konfiguriert",
    "interactive.bonus_backup": "Bonus: Datenbank-Backup-Job wird hinzugefügt",
    "interactive.backup_desc": (
        "Täglicher Datenbank-Backup-Job enthalten (läuft um 2 Uhr)"
    ),
    # ── Interactive: database engine ───────────────────────────────────
    "interactive.db_engine_label": "{context} Datenbank-Engine:",
    "interactive.db_select": "Datenbank-Engine wählen:",
    "interactive.db_sqlite": "SQLite – Einfach, dateibasiert (gut für Entwicklung)",
    "interactive.db_postgres": (
        "PostgreSQL – Produktionsreif, Multi-Container-Unterstützung"
    ),
    "interactive.db_reuse": "Nutze zuvor gewählte Datenbank: {engine}",
    "interactive.db_provider_select": "PostgreSQL-Host auswählen:",
    "interactive.db_provider_container": (
        "Lokaler Container - postgres:16 in Docker (Dev und Prod)"
    ),
    "interactive.db_provider_neon": (
        "Neon - serverloses Postgres (Cloud in Prod, lokaler Container in Dev)"
    ),
    # ── Interactive: worker backend ────────────────────────────────────
    "interactive.worker_label": "Worker Backend:",
    "interactive.worker_select": "Worker Backend wählen:",
    "interactive.worker_arq": "arq – Async, leichtgewichtig (Standard)",
    "interactive.worker_dramatiq": (
        "Dramatiq – Prozessbasiert, ideal für CPU-lastige Aufgaben"
    ),
    "interactive.worker_taskiq": (
        "TaskIQ – Async, Framework-Stil mit Queue-spezifischen Brokern"
    ),
    # ── Interactive: auth ──────────────────────────────────────────────
    "interactive.auth_header": "Authentifizierungsdienste:",
    "interactive.auth_level_label": "Authentifizierungsstufe:",
    "interactive.auth_select": "Welche Art der Authentifizierung?",
    "interactive.auth_basic": "Basis – E-Mail/Passwort-Login",
    "interactive.auth_rbac": "Mit Rollen – + rollenbasierte Zugriffskontrolle (experimentell)",
    "interactive.auth_org": "Mit Organisationen – + Mandantenfähigkeit (experimentell)",
    "interactive.auth_selected": "Gewählte Auth-Stufe: {level}",
    "interactive.auth_db_required": "Datenbank benötigt:",
    "interactive.auth_db_reason": (
        "Authentifizierung benötigt eine Datenbank für Benutzerspeicherung"
    ),
    "interactive.auth_db_details": "(Benutzerkonten, Sessions, JWT-Tokens)",
    "interactive.auth_db_already": "Datenbankkomponente bereits ausgewählt",
    "interactive.auth_db_confirm": "Fortfahren und Datenbankkomponente hinzufügen?",
    "interactive.auth_cancelled": "Authentifizierungsservice abgebrochen",
    "interactive.auth_db_configured": "Authentifizierung + Datenbank konfiguriert",
    # ── Interactive: AI service ────────────────────────────────────────
    "interactive.ai_header": "AI & Machine-Learning-Services:",
    "interactive.ai_framework_label": "AI Framework-Auswahl:",
    "interactive.ai_framework_intro": "AI Framework wählen:",
    "interactive.ai_pydanticai": ("PydanticAI – Typsicher, pythonisch (empfohlen)"),
    "interactive.ai_langchain": (
        "LangChain – Beliebtes Framework mit umfangreichen Integrationen"
    ),
    "interactive.ai_use_pydanticai": "PydanticAI verwenden? (empfohlen)",
    "interactive.ai_selected_framework": "Gewähltes Framework: {framework}",
    "interactive.ai_tracking_context": "AI Nutzungsverfolgung",
    "interactive.ai_tracking_label": "LLM Nutzungsverfolgung:",
    "interactive.ai_tracking_prompt": (
        "Nutzungsverfolgung aktivieren? (Token-Zählung, Kosten, Gesprächsverlauf)"
    ),
    "interactive.ai_sync_label": "LLM-Katalog-Sync:",
    "interactive.ai_sync_desc": (
        "Sync ruft aktuelle Modelldaten von OpenRouter/LiteLLM APIs ab"
    ),
    "interactive.ai_sync_time": (
        "Benötigt Netzwerkzugang und dauert ca. 30–60 Sekunden"
    ),
    "interactive.ai_sync_prompt": "LLM-Katalog bei Projektgenerierung synchronisieren?",
    "interactive.ai_sync_will": "LLM-Katalog wird nach Projektgenerierung synchronisiert",
    "interactive.ai_sync_skipped": (
        "LLM-Sync übersprungen – statische Fixture-Daten verfügbar"
    ),
    "interactive.ai_provider_label": "AI Provider-Auswahl:",
    "interactive.ai_provider_intro": ("AI Provider wählen (Mehrfachauswahl möglich)"),
    "interactive.ai_provider_options": "Provider-Optionen:",
    "interactive.ai_provider_recommended": "(Empfohlen)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI – GPT-Modelle (kostenpflichtig)",
    "interactive.ai_provider.anthropic": "Anthropic – Claude-Modelle (kostenpflichtig)",
    "interactive.ai_provider.google": "Google – Gemini-Modelle (kostenlose Stufe)",
    "interactive.ai_provider.groq": "Groq – Schnelle Inferenz (kostenlose Stufe)",
    "interactive.ai_provider.mistral": "Mistral – Offene Modelle (überwiegend kostenpflichtig)",
    "interactive.ai_provider.cohere": "Cohere – Enterprise-Fokus (begrenzt kostenlos)",
    "interactive.ai_provider.ollama": "Ollama – Lokale Inferenz (kostenlos)",
    "interactive.ai_no_providers": (
        "Keine Provider gewählt, füge empfohlene Standardwerte hinzu..."
    ),
    "interactive.ai_selected_providers": "Gewählte Provider: {providers}",
    "interactive.ai_deps_optimized": (
        "Abhängigkeiten werden für deine Auswahl optimiert"
    ),
    "interactive.ai_ollama_label": "Ollama Deployment-Modus:",
    "interactive.ai_ollama_intro": "Wie möchtest du Ollama betreiben?",
    "interactive.ai_ollama_host": (
        "Host – Verbindung zu Ollama auf deinem Rechner (Mac/Windows)"
    ),
    "interactive.ai_ollama_docker": (
        "Docker – Ollama im Docker-Container ausführen (Linux/Deploy)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "Mit Host-Ollama verbinden? (empfohlen für Mac/Windows)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama verbindet sich mit host.docker.internal:11434"
    ),
    "interactive.ai_ollama_host_hint": "Stelle sicher, dass Ollama läuft: ollama serve",
    "interactive.ai_ollama_docker_ok": (
        "Ollama Service wird zu docker-compose.yml hinzugefügt"
    ),
    "interactive.ai_ollama_docker_hint": (
        "Hinweis: Erster Start kann Zeit für den Modell-Download benötigen"
    ),
    "interactive.ai_rag_label": "RAG (Retrieval-Augmented Generation):",
    "interactive.ai_rag_warning": (
        "Warnung: RAG benötigt Python <3.14 (chromadb/onnxruntime-Einschränkung)"
    ),
    "interactive.ai_rag_compat_note": (
        "RAG aktivieren generiert ein Projekt, das Python 3.11–3.13 benötigt"
    ),
    "interactive.ai_rag_compat_prompt": (
        "RAG trotz Python-3.14-Inkompatibilität aktivieren?"
    ),
    "interactive.ai_rag_prompt": (
        "RAG für Dokumentenindexierung und semantische Suche aktivieren?"
    ),
    "interactive.ai_rag_enabled": "RAG mit ChromaDB Vector Store aktiviert",
    "interactive.ai_voice_label": "Voice (Text-to-Speech & Speech-to-Text):",
    "interactive.ai_voice_prompt": (
        "Voice-Funktionen aktivieren? (TTS und STT für Sprachinteraktionen)"
    ),
    "interactive.ai_voice_enabled": "Voice mit TTS- und STT-Unterstützung aktiviert",
    "interactive.ai_db_already": "Datenbank bereits gewählt – Nutzungsverfolgung aktiviert",
    "interactive.ai_db_added": "Datenbank ({backend}) für Nutzungsverfolgung hinzugefügt",
    "interactive.ai_configured": "AI Service konfiguriert",
    # ── Shared: validation ──────────────────────────────────────────────
    "shared.not_copier_project": "Projekt in {path} nicht mit Copier generiert.",
    "shared.copier_only": (
        "Der Befehl 'aegis {command}' funktioniert nur mit Copier-generierten Projekten."
    ),
    "shared.regenerate_hint": (
        "Um Komponenten hinzuzufügen, generiere das Projekt mit den neuen Komponenten neu."
    ),
    "shared.git_not_initialized": "Projekt ist nicht in einem Git-Repository",
    "shared.git_required": "Copier-Updates benötigen Git zur Änderungsverfolgung",
    "shared.git_init_hint": (
        "Mit 'aegis init' erstellte Projekte sollten Git automatisch initialisiert haben"
    ),
    "shared.git_manual_init": (
        "Falls manuell erstellt, ausführen: "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "Leerer Komponentenname ist nicht erlaubt",
    "shared.empty_service": "Leerer Service-Name ist nicht erlaubt",
    # ── Shared: next steps / review ──────────────────────────────────
    "shared.next_steps": "Nächste Schritte:",
    "shared.next_make_check": "   1. 'make check' ausführen, um das Update zu prüfen",
    "shared.next_test": "   2. Anwendung testen",
    "shared.next_commit": "   3. Änderungen committen: git add . && git commit",
    "shared.review_header": "Änderungen prüfen:",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "Vorgang abgebrochen",
    "shared.interactive_ignores_args": (
        "Warnung: --interactive ignoriert Komponenten-Argumente"
    ),
    "shared.no_components_selected": "Keine Komponenten ausgewählt",
    "shared.no_services_selected": "Keine Services ausgewählt",
    # ── Add command ──────────────────────────────────────────────────
    "add.title": "Aegis Stack – Komponenten hinzufügen",
    "add.project": "Projekt: {path}",
    "add.error_no_args": (
        "Fehler: Komponenten-Argument benötigt (oder --interactive nutzen)"
    ),
    "add.usage_hint": "Nutzung: aegis add scheduler,worker",
    "add.interactive_hint": "Oder: aegis add --interactive",
    "add.auto_added_deps": "Automatisch hinzugefügte Abhängigkeiten: {deps}",
    "add.validation_failed": "Komponentenvalidierung fehlgeschlagen: {error}",
    "add.load_config_failed": "Projektkonfiguration konnte nicht geladen werden: {error}",
    "add.already_enabled": "Bereits aktiviert: {components}",
    "add.all_enabled": "Alle angeforderten Komponenten sind bereits aktiviert!",
    "add.components_to_add": "Hinzuzufügende Komponenten:",
    "add.scheduler_backend": "Scheduler Backend: {backend}",
    "add.confirm": "Diese Komponenten hinzufügen?",
    "add.updating": "Aktualisiere Projekt...",
    "add.adding": "Füge {component} hinzu...",
    "add.added_files": "{count} Dateien hinzugefügt",
    "add.skipped_files": "{count} vorhandene Dateien übersprungen",
    "add.success": "Komponenten hinzugefügt!",
    "add.failed_component": "{component} konnte nicht hinzugefügt werden: {error}",
    "add.failed": "Komponenten konnten nicht hinzugefügt werden: {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "Ungültiges Komponentenformat: {error}",
    "add.bracket_override": (
        "Klammersyntax 'scheduler[{engine}]' überschreibt --backend {backend}"
    ),
    "add.invalid_scheduler_backend": "Ungültiges Scheduler Backend: '{backend}'",
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "Gültige Optionen: {options}",
    "add.postgres_coming": "Hinweis: PostgreSQL-Unterstützung kommt in einer zukünftigen Version",
    "add.auto_added_db": "Datenbankkomponente für Scheduler-Persistenz automatisch hinzugefügt",
    "add.generated_migration": "Migration generiert: {name}",
    "add.scheduler_db_engine_mismatch": "Scheduler-Backend '{backend}' kann nicht verwendet werden: Die Datenbank-Engine des Projekts ist '{engine}'. Sie müssen übereinstimmen.",
    # ── Remove command ────────────────────────────────────────────────
    "remove.title": "Aegis Stack – Komponenten entfernen",
    "remove.project": "Projekt: {path}",
    "remove.error_no_args": (
        "Fehler: Komponenten-Argument benötigt (oder --interactive nutzen)"
    ),
    "remove.usage_hint": "Nutzung: aegis remove scheduler,worker",
    "remove.interactive_hint": "Oder: aegis remove --interactive",
    "remove.no_selected": "Keine Komponenten zum Entfernen ausgewählt",
    "remove.validation_failed": "Komponentenvalidierung fehlgeschlagen: {error}",
    "remove.load_config_failed": "Projektkonfiguration konnte nicht geladen werden: {error}",
    "remove.cannot_remove_core": "Kernkomponente kann nicht entfernt werden: {component}",
    "remove.not_enabled": "Nicht aktiviert: {components}",
    "remove.nothing_to_remove": "Keine Komponenten zum Entfernen!",
    "remove.auto_remove_redis": (
        "Entferne Redis automatisch (keine eigenständige Funktion, nur vom Worker genutzt)"
    ),
    "remove.scheduler_persistence_warn": "WICHTIG: Warnung zur Scheduler-Persistenz",
    "remove.scheduler_persistence_detail": (
        "Dein Scheduler nutzt SQLite für Job-Persistenz."
    ),
    "remove.scheduler_db_remains": (
        "Die Datenbankdatei unter data/scheduler.db bleibt erhalten."
    ),
    "remove.scheduler_keep_hint": (
        "Um den Job-Verlauf zu behalten: Datenbankkomponente beibehalten"
    ),
    "remove.scheduler_remove_hint": (
        "Um alle Daten zu entfernen: Auch die Datenbankkomponente entfernen"
    ),
    "remove.components_to_remove": "Zu entfernende Komponenten:",
    "remove.warning_delete": (
        "WARNUNG: Komponentendateien werden aus dem Projekt GELÖSCHT!"
    ),
    "remove.commit_hint": "Stelle sicher, dass du deine Änderungen committet hast.",
    "remove.confirm": "Diese Komponenten entfernen?",
    "remove.removing_all": "Entferne Komponenten...",
    "remove.removing": "Entferne {component}...",
    "remove.removed_files": "{count} Dateien entfernt",
    "remove.failed_component": "{component} konnte nicht entfernt werden: {error}",
    "remove.success": "Komponenten entfernt!",
    "remove.failed": "Komponenten konnten nicht entfernt werden: {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Manual updater ─────────────────────────────────────────────────
    "updater.processing_files": "Verarbeite {count} Komponentendateien...",
    "updater.updating_shared": "Aktualisiere gemeinsame Template-Dateien...",
    "updater.shared_preserved": "Lokale Änderungen beibehalten (Regenerierung übersprungen, manuell zusammenführen): {file}",
    "updater.shared_merged": "Template-Änderungen in deine angepasste Datei zusammengeführt: {file}",
    "updater.shared_conflict": "Merge-Konflikt (Markierungen geschrieben, manuell auflösen): {file}",
    "updater.running_postgen": "Führe Nachgenerierungsaufgaben aus...",
    "updater.deps_synced": "Abhängigkeiten synchronisiert (uv sync)",
    "updater.code_formatted": "Code formatiert (make fix)",
    # ── Project map ──────────────────────────────────────────────────
    "projectmap.new": "NEU",
    # ── Post-generation: setup tasks ──────────────────────────────────
    "postgen.setup_start": "Projektumgebung wird eingerichtet...",
    "postgen.deps_installing": "Installiere Abhängigkeiten mit uv...",
    "postgen.deps_success": "Abhängigkeiten installiert",
    "postgen.deps_failed": "Projektgenerierung fehlgeschlagen: Abhängigkeitsinstallation fehlgeschlagen",
    "postgen.deps_failed_detail": (
        "Die generierten Projektdateien sind vorhanden, aber das Projekt ist nicht nutzbar."
    ),
    "postgen.deps_failed_hint": (
        "Behebe das Abhängigkeitsproblem (Python-Versionskompatibilität prüfen) und versuche es erneut."
    ),
    "postgen.deps_warn_failed": "Warnung: Abhängigkeitsinstallation fehlgeschlagen",
    "postgen.deps_manual": "Führe 'uv sync' manuell nach Projekterstellung aus",
    "postgen.deps_timeout": (
        "Warnung: Timeout bei Abhängigkeitsinstallation – 'uv sync' manuell ausführen"
    ),
    "postgen.deps_uv_missing": "Warnung: uv nicht im PATH gefunden",
    "postgen.deps_uv_install": "Zuerst uv installieren: https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "Warnung: Abhängigkeitsinstallation fehlgeschlagen: {error}",
    "postgen.env_setup": "Richte Umgebungskonfiguration ein...",
    "postgen.env_created": "Umgebungsdatei aus .env.example erstellt",
    "postgen.env_exists": "Umgebungsdatei existiert bereits",
    "postgen.env_missing": "Warnung: Keine .env.example Datei gefunden",
    "postgen.env_error": "Warnung: Umgebungseinrichtung fehlgeschlagen: {error}",
    "postgen.env_manual": ".env.example manuell nach .env kopieren",
    # ── Post-generation: database/migrations ────────────────────────────
    "postgen.db_setup": "Richte Datenbankschema ein...",
    "postgen.db_success": "Datenbanktabellen erstellt",
    "postgen.db_alembic_missing": "Warnung: Alembic-Konfigurationsdatei nicht gefunden unter {path}",
    "postgen.db_alembic_hint": (
        "Überspringe Datenbankmigration. Stelle sicher, dass die Konfigurationsdatei existiert "
        "und führe 'alembic upgrade head' manuell aus."
    ),
    "postgen.db_failed": "Warnung: Datenbankmigration fehlgeschlagen",
    "postgen.db_manual": "Führe 'alembic upgrade head' manuell nach Projekterstellung aus",
    "postgen.db_timeout": (
        "Warnung: Timeout bei Migrationseinrichtung – 'alembic upgrade head' manuell ausführen"
    ),
    "postgen.db_error": "Warnung: Migrationseinrichtung fehlgeschlagen: {error}",
    # ── Post-generation: LLM fixtures/sync ────────────────────────────
    "postgen.llm_seeding": "Lade LLM-Fixtures...",
    "postgen.llm_seed_success": "LLM-Fixtures geladen",
    "postgen.llm_seed_failed": "Warnung: LLM-Fixture-Laden fehlgeschlagen",
    "postgen.llm_seed_manual": (
        "Fixtures können manuell über den Fixture-Loader geladen werden"
    ),
    "postgen.llm_seed_timeout": "Warnung: Timeout beim LLM-Fixture-Laden",
    "postgen.llm_seed_error": "Warnung: LLM-Fixture-Laden fehlgeschlagen: {error}",
    "postgen.llm_syncing": "Synchronisiere LLM-Katalog von externen APIs...",
    "postgen.llm_sync_success": "LLM-Katalog synchronisiert",
    "postgen.llm_sync_failed": "Warnung: LLM-Katalog-Sync fehlgeschlagen",
    "postgen.llm_sync_manual": (
        "Führe '{slug} llm sync' manuell aus, um den Katalog zu befüllen"
    ),
    "postgen.llm_sync_timeout": "Warnung: Timeout beim LLM-Katalog-Sync",
    "postgen.llm_sync_error": "Warnung: LLM-Katalog-Sync fehlgeschlagen: {error}",
    # ── Post-generation: formatting ───────────────────────────────────
    "postgen.format_timeout": (
        "Warnung: Timeout bei Formatierung – 'make fix' manuell ausführen"
    ),
    "postgen.format_error": "Warnung: Autoformatierung übersprungen: {error}",
    "postgen.format_error_manual": "Führe 'make fix' manuell aus, um Code zu formatieren",
    "postgen.format_start": "Formatiere generierten Code...",
    "postgen.format_success": "Code-Formatierung abgeschlossen",
    "postgen.format_partial": (
        "Einige Formatierungsprobleme erkannt, aber Projekt erstellt"
    ),
    "postgen.format_manual": "Führe 'make fix' manuell aus, um verbleibende Probleme zu beheben",
    "postgen.format_hint": "Führe 'make fix' aus, um Code zu formatieren",
    "postgen.llm_sync_skipped": "LLM-Katalog-Sync übersprungen",
    "postgen.llm_fixtures_outdated": "Statische Fixture-Daten geladen (möglicherweise veraltet)",
    "postgen.llm_sync_hint": "Führe '{slug} llm sync' später aus, um aktuelle Modelldaten zu erhalten",
    "postgen.llm_fixtures_fallback": (
        "Statische Fixture-Daten verfügbar, aber möglicherweise veraltet"
    ),
    "postgen.ready": "Projekt bereit!",
    "postgen.next_steps": "Nächste Schritte:",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Overseer öffnen: http://localhost:8000/dashboard/",
    # ── Post-generation: project map ──────────────────────────────────
    "projectmap.title": "Projektstruktur:",
    "projectmap.components": "Komponenten",
    "projectmap.services": "Geschäftslogik",
    "projectmap.models": "Datenbankmodelle",
    "projectmap.cli": "CLI-Befehle",
    "projectmap.entrypoints": "Einstiegspunkte",
    "projectmap.tests": "Testsammlung",
    "projectmap.migrations": "Migrationen",
    "projectmap.auth": "Authentifizierung",
    "projectmap.ai": "AI-Konversationen",
    "projectmap.comms": "Kommunikation",
    "projectmap.docs": "Dokumentation",
    # ── Post-generation: footer ───────────────────────────────────────
    "postgen.docs_link": "Doku: https://docs.aegis-stack.io",
    "postgen.star_prompt": (
        "Falls Aegis Stack dir geholfen hat, hinterlasse gerne einen Stern:"
    ),
    # ── Add-service command ────────────────────────────────────────────
    "add_service.title": "Aegis Stack – Services hinzufügen",
    "add_service.project": "Projekt: {path}",
    "add_service.error_no_args": (
        "Fehler: Services-Argument benötigt (oder --interactive nutzen)"
    ),
    "add_service.usage_hint": "Nutzung: aegis add-service auth,ai",
    "add_service.interactive_hint": "Oder: aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "Warnung: --interactive ignoriert Service-Argumente"
    ),
    "add_service.no_selected": "Keine Services ausgewählt",
    "add_service.already_enabled": "Bereits aktiviert: {services}",
    "add_service.all_enabled": "Alle angeforderten Services sind bereits aktiviert!",
    "add_service.validation_failed": "Service-Validierung fehlgeschlagen: {error}",
    "add_service.load_config_failed": "Projektkonfiguration konnte nicht geladen werden: {error}",
    "add_service.services_to_add": "Hinzuzufügende Services:",
    "add_service.required_components": "Benötigte Komponenten (werden automatisch hinzugefügt):",
    "add_service.already_have_components": (
        "Benötigte Komponenten bereits vorhanden: {components}"
    ),
    "add_service.confirm": "Diese Services hinzufügen?",
    "add_service.adding_component": "Füge benötigte Komponente hinzu: {component}...",
    "add_service.failed_component": "Komponente {component} konnte nicht hinzugefügt werden: {error}",
    "add_service.added_files": "{count} Dateien hinzugefügt",
    "add_service.skipped_files": "{count} vorhandene Dateien übersprungen",
    "add_service.preserved_files": "{count} gemeinsame Datei(en) benötigen manuelle Prüfung (siehe Meldungen oben)",
    "add_service.adding_service": "Füge Service hinzu: {service}...",
    "add_service.failed_service": "Service {service} konnte nicht hinzugefügt werden: {error}",
    "add_service.resolve_failed": "Service-Abhängigkeiten konnten nicht aufgelöst werden: {error}",
    "add_service.bootstrap_alembic": "Richte Alembic-Infrastruktur ein...",
    "add_service.created_file": "Erstellt: {file}",
    "add_service.generated_migration": "Migration generiert: {name}",
    "add_service.applying_migrations": "Wende Datenbankmigrationen an...",
    "add_service.migration_failed": (
        "Warnung: Auto-Migration fehlgeschlagen. Führe 'make migrate' manuell aus."
    ),
    "add_service.success": "Services hinzugefügt!",
    "add_service.failed": "Services konnten nicht hinzugefügt werden: {error}",
    "add_service.auth_setup": "Auth Service Einrichtung:",
    "add_service.auth_create_users": "   1. Testbenutzer erstellen: {cmd}",
    "add_service.auth_view_routes": "   2. Auth-Routen anzeigen: {url}",
    "add_service.ai_setup": "AI Service Einrichtung:",
    "add_service.ai_set_provider": (
        "   1. {env_var} in .env setzen (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": "   2. Provider-API-Key setzen ({env_var} usw.)",
    "add_service.ai_test_cli": "   3. Per CLI testen: {cmd}",
    # ── Remove-service command ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack – Services entfernen",
    "remove_service.project": "Projekt: {path}",
    "remove_service.error_no_args": (
        "Fehler: Services-Argument benötigt (oder --interactive nutzen)"
    ),
    "remove_service.usage_hint": "Nutzung: aegis remove-service auth,ai",
    "remove_service.interactive_hint": "Oder: aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "Warnung: --interactive ignoriert Service-Argumente"
    ),
    "remove_service.no_selected": "Keine Services zum Entfernen ausgewählt",
    "remove_service.not_enabled": "Nicht aktiviert: {services}",
    "remove_service.nothing_to_remove": "Keine Services zum Entfernen!",
    "remove_service.validation_failed": "Service-Validierung fehlgeschlagen: {error}",
    "remove_service.load_config_failed": (
        "Projektkonfiguration konnte nicht geladen werden: {error}"
    ),
    "remove_service.services_to_remove": "Zu entfernende Services:",
    "remove_service.auth_warning": "WICHTIG: Warnung zum Auth Service",
    "remove_service.auth_delete_intro": "Entfernen des Auth Service löscht:",
    "remove_service.auth_delete_endpoints": "Benutzerauthentifizierungs-API-Endpunkte",
    "remove_service.auth_delete_models": "Benutzermodell und Authentifizierungsdienste",
    "remove_service.auth_delete_jwt": "JWT-Token-Verarbeitungscode",
    "remove_service.auth_db_note": (
        "Hinweis: Datenbanktabellen und Alembic-Migrationen werden NICHT gelöscht."
    ),
    "remove_service.warning_delete": (
        "WARNUNG: Service-Dateien werden aus dem Projekt GELÖSCHT!"
    ),
    "remove_service.confirm": "Diese Services entfernen?",
    "remove_service.removing": "Entferne Service: {service}...",
    "remove_service.failed_service": "Service {service} konnte nicht entfernt werden: {error}",
    "remove_service.removed_files": "{count} Dateien entfernt",
    "remove_service.success": "Services entfernt!",
    "remove_service.failed": "Services konnten nicht entfernt werden: {error}",
    "remove_service.deps_not_removed": (
        "Hinweis: Service-Abhängigkeiten (Datenbank usw.) NICHT entfernt."
    ),
    "remove_service.deps_remove_hint": (
        "Nutze 'aegis remove <component>', um Komponenten einzeln zu entfernen."
    ),
    # ── Version command ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Components command ─────────────────────────────────────────────
    "components.core_title": "KERNKOMPONENTEN",
    "components.backend_desc": (
        "  backend      - FastAPI Backend-Server (immer enthalten)"
    ),
    "components.frontend_desc": (
        "  frontend     - Flet Frontend-Oberfläche (immer enthalten)"
    ),
    "components.infra_title": "INFRASTRUKTURKOMPONENTEN",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "Benötigt: {deps}",
    "components.recommends": "Empfohlen: {deps}",
    "components.usage_hint": (
        "Nutze 'aegis init PROJEKTNAME --components redis,worker' zur Komponentenauswahl"
    ),
    # ── Services command ───────────────────────────────────────────────
    "services.title": "VERFÜGBARE SERVICES",
    "services.type_auth": "Authentifizierungsdienste",
    "services.type_payment": "Zahlungsdienste",
    "services.type_ai": "AI & Machine-Learning-Services",
    "services.type_notification": "Benachrichtigungsdienste",
    "services.type_analytics": "Analysedienste",
    "services.type_storage": "Speicherdienste",
    "services.type_content": "Content-Dienste",
    "services.type_finance": "Finanzdienste",
    "services.requires_components": "Benötigt Komponenten: {deps}",
    "services.recommends_components": "Empfiehlt Komponenten: {deps}",
    "services.requires_services": "Benötigt Services: {deps}",
    "services.none_available": "  Noch keine Services verfügbar.",
    "services.usage_hint": (
        "Nutze 'aegis init PROJEKTNAME --services auth' zum Hinzufügen von Services"
    ),
    # ── Update command ─────────────────────────────────────────────────
    "update.title": "Aegis Stack – Template aktualisieren",
    "update.not_copier": "Projekt in {path} nicht mit Copier generiert.",
    "update.copier_only": (
        "Der Befehl 'aegis update' funktioniert nur mit Copier-generierten Projekten."
    ),
    "update.need_regen": "Projekte vor v0.2.0 müssen neu generiert werden.",
    "update.project": "Projekt: {path}",
    "update.commit_or_stash": (
        "Committe oder stashe deine Änderungen vor 'aegis update'."
    ),
    "update.clean_required": (
        "Copier benötigt einen sauberen Git-Baum für sicheres Mergen."
    ),
    "update.git_clean": "Git-Baum ist sauber",
    "update.dirty_tree": "Git-Baum hat uncommittete Änderungen",
    "update.changelog_breaking": "Breaking Changes:",
    "update.changelog_features": "Neue Features:",
    "update.changelog_fixes": "Bugfixes:",
    "update.changelog_other": "Sonstige Änderungen:",
    "update.current_commit": "   Aktuell: {commit}...",
    "update.target_commit": "   Ziel:    {commit}...",
    "update.unknown_version": "Warnung: Aktuelle Template-Version nicht ermittelbar",
    "update.untagged_commit": (
        "Projekt möglicherweise aus einem ungetaggten Commit generiert"
    ),
    "update.custom_template": "Nutze benutzerdefiniertes Template ({source}): {path}",
    "update.version_info": "Versionsinformationen:",
    "update.current_cli": "   Aktuelle CLI:      {version}",
    "update.current_template": "   Aktuelles Template: {version}",
    "update.current_template_commit": "   Aktuelles Template: {commit}... (Commit)",
    "update.current_template_unknown": "   Aktuelles Template: unbekannt",
    "update.target_template": "   Ziel-Template:      {version}",
    "update.already_at_version": "Projekt ist bereits auf der angeforderten Version",
    "update.already_at_commit": "Projekt ist bereits auf dem Ziel-Commit",
    "update.ahead_of_target": ("Projekt ist neuer als die Ziel-Template-Version"),
    "update.ahead_of_target_hint": (
        "Nichts zu aktualisieren. Mit --to-version eine bestimmte Version wählen."
    ),
    "update.downgrade_blocked": "Downgrade nicht unterstützt",
    "update.downgrade_reason": (
        "Copier unterstützt kein Downgrade auf ältere Template-Versionen."
    ),
    "update.changelog": "Changelog:",
    "update.dry_run": "TROCKENLAUF – Keine Änderungen werden angewendet",
    "update.dry_run_hint": "Um dieses Update anzuwenden, ausführen:",
    "update.confirm": "Dieses Update anwenden?",
    "update.cancelled": "Update abgebrochen",
    "update.creating_backup": "Erstelle Backup-Punkt...",
    "update.backup_created": "   Backup erstellt: {tag}",
    "update.backup_failed": "Backup-Punkt konnte nicht erstellt werden",
    "update.updating": "Aktualisiere Projekt...",
    "update.updating_to": "Aktualisiere auf Template-Version {version}",
    "update.moved_files": "   {count} neue Dateien aus verschachteltem Verzeichnis verschoben",
    "update.synced_files": "   {count} Template-Änderungen synchronisiert",
    "update.merge_conflicts": (
        "   {count} Datei(en) haben Merge-Konflikte (nach <<<<<<< suchen):"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "Führe Nachgenerierungsaufgaben aus...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": "   __aegis_version__ auf {version} aktualisiert",
    "update.success": "Update abgeschlossen!",
    "update.partial_success": (
        "Update abgeschlossen, einige Nachgenerierungsaufgaben fehlgeschlagen"
    ),
    "update.partial_detail": "   Einige Einrichtungsaufgaben fehlgeschlagen. Siehe Details oben.",
    "update.next_steps": "Nächste Schritte:",
    "update.next_review": "   1. Änderungen prüfen: git diff",
    "update.next_conflicts": "   2. Auf Konflikte prüfen (*.rej Dateien)",
    "update.next_test": "   3. Tests ausführen: make check",
    "update.next_commit": "   4. Änderungen committen: git add . && git commit",
    "update.failed": "Update fehlgeschlagen: {error}",
    "update.rollback_prompt": "Auf vorherigen Zustand zurücksetzen?",
    "update.manual_rollback": "Manueller Rollback: git reset --hard {tag}",
    "update.troubleshooting": "Fehlerbehebung:",
    "update.troubleshoot_clean": "   - Sauberen Git-Baum sicherstellen",
    "update.troubleshoot_version": "   - Prüfen, ob Version/Commit existiert",
    "update.troubleshoot_docs": "   - Copier-Dokumentation zu Update-Problemen lesen",
    # ── Ingress command ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack – Ingress TLS aktivieren",
    "ingress.project": "Projekt: {path}",
    "ingress.not_found": "Ingress-Komponente nicht gefunden. Wird zuerst hinzugefügt...",
    "ingress.add_confirm": "Ingress-Komponente hinzufügen?",
    "ingress.add_failed": "Ingress-Komponente konnte nicht hinzugefügt werden: {error}",
    "ingress.added": "Ingress-Komponente hinzugefügt.",
    "ingress.tls_already": "TLS ist in diesem Projekt bereits aktiviert.",
    "ingress.domain_label": "   Domain: {domain}",
    "ingress.acme_email": "   ACME E-Mail: {email}",
    "ingress.domain_prompt": (
        "Domainname (z.B. example.com, oder leer für IP-basiertes Routing)"
    ),
    "ingress.email_reuse": "Nutze vorhandene E-Mail für ACME: {email}",
    "ingress.email_prompt": "E-Mail für Let's-Encrypt-Benachrichtigungen",
    "ingress.email_required": (
        "Fehler: --email ist für TLS benötigt (für Let's Encrypt)"
    ),
    "ingress.tls_config": "TLS-Konfiguration:",
    "ingress.domain_none": "   Domain: (keine – IP/PathPrefix-Routing)",
    "ingress.tls_confirm": "TLS mit dieser Konfiguration aktivieren?",
    "ingress.enabling": "Aktiviere TLS...",
    "ingress.updated_file": "   Aktualisiert: {file}",
    "ingress.created_file": "   Erstellt: {file}",
    "ingress.success": "TLS aktiviert!",
    "ingress.available_at": "   Deine App ist erreichbar unter: https://{domain}",
    "ingress.https_configured": "   HTTPS ist jetzt mit Let's Encrypt konfiguriert",
    "ingress.next_steps": "Nächste Schritte:",
    "ingress.next_deploy": "   1. Deployen mit: aegis deploy",
    "ingress.next_ports": "   2. Ports 80 und 443 auf dem Server freigeben",
    "ingress.next_dns": (
        "   3. DNS-A-Record für {domain} auf die Server-IP zeigen lassen"
    ),
    "ingress.next_certs": "   Zertifikate werden bei der ersten Anfrage automatisch bereitgestellt",
    # ── Deploy commands ────────────────────────────────────────────────
    "deploy.no_config": (
        "Keine Deploy-Konfiguration gefunden. Zuerst 'aegis deploy-init' ausführen."
    ),
    "deploy.init_saved": "Deploy-Konfiguration in {file} gespeichert",
    "deploy.init_host": "   Host: {host}",
    "deploy.init_user": "   Benutzer: {user}",
    "deploy.init_path": "   Pfad: {path}",
    "deploy.init_docker_context": "   Docker Context: {context}",
    "deploy.prompt_host": "Server-IP oder Hostname",
    "deploy.init_gitignore": (
        "Hinweis: .aegis/ in .gitignore aufnehmen, um Deploy-Konfiguration nicht zu committen"
    ),
    "deploy.setup_title": "Richte Server ein unter {target}...",
    "deploy.checking_ssh": "Prüfe SSH-Verbindung...",
    "deploy.adding_host_key": "Füge Server zu known_hosts hinzu...",
    "deploy.ssh_keyscan_failed": "SSH-Host-Key-Scan fehlgeschlagen: {error}",
    "deploy.ssh_failed": "SSH-Verbindung fehlgeschlagen: {error}",
    "deploy.copying_script": "Kopiere Setup-Script auf Server...",
    "deploy.copy_failed": "Kopieren des Setup-Scripts fehlgeschlagen",
    "deploy.running_setup": "Führe Server-Setup aus (kann einige Minuten dauern)...",
    "deploy.setup_failed": "Server-Setup fehlgeschlagen",
    "deploy.setup_script_missing": "Server-Setup-Script nicht gefunden: {path}",
    "deploy.setup_script_hint": (
        "Stelle sicher, dass das Projekt mit der Ingress-Komponente erstellt wurde."
    ),
    "deploy.setup_complete": "Server-Setup abgeschlossen!",
    "deploy.setup_verify": "Prüfe Installation:",
    "deploy.setup_verify_docker": "  Docker: {version}",
    "deploy.setup_verify_compose": "  Docker Compose: {version}",
    "deploy.setup_verify_uv": "  uv: {version}",
    "deploy.setup_verify_app_dir": "  App-Verzeichnis: {path}",
    "deploy.setup_next": "Weiter: 'aegis deploy' ausführen, um die Anwendung zu deployen",
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
    "deploy.deploying": "Deploye nach {host}...",
    "deploy.creating_backup": "Erstelle Backup {timestamp}...",
    "deploy.backup_failed": "Backup fehlgeschlagen: {error}",
    "deploy.backup_db": "Sichere PostgreSQL-Datenbank...",
    "deploy.backup_db_neon": "Datenbank wird von Neon verwaltet (Branches / Point-in-Time-Restore); lokales Backup wird übersprungen",
    "deploy.backup_db_failed": (
        "Warnung: Datenbank-Backup fehlgeschlagen, fahre ohne fort"
    ),
    "deploy.backup_created": "Backup erstellt: {timestamp}",
    "deploy.backup_pruned": "Altes Backup entfernt: {name}",
    "deploy.no_existing": "Kein vorhandenes Deployment gefunden, überspringe Backup",
    "deploy.syncing": "Synchronisiere Dateien zum Server...",
    "deploy.mkdir_failed": "Remote-Verzeichnis '{path}' konnte nicht erstellt werden",
    "deploy.sync_failed": "Dateisynchronisierung fehlgeschlagen",
    "deploy.copying_env": "Kopiere {file} als .env auf den Server...",
    "deploy.env_copy_failed": "Kopieren der .env-Datei fehlgeschlagen",
    "deploy.stopping": "Stoppe laufende Services...",
    "deploy.building": "Baue und starte Services auf dem Server...",
    "deploy.start_failed": "Services konnten nicht gestartet werden",
    "deploy.auto_rollback": "Automatischer Rollback auf vorherige Version...",
    "deploy.health_waiting": "Warte auf Container-Stabilisierung...",
    "deploy.health_attempt": "Health Check Versuch {n}/{total}...",
    "deploy.health_passed": "Health Check bestanden",
    "deploy.health_retry": "Health Check fehlgeschlagen, neuer Versuch in {interval}s...",
    "deploy.health_all_failed": "Alle Health-Check-Versuche fehlgeschlagen",
    "deploy.rolled_back": "Rollback auf Backup {timestamp} durchgeführt",
    "deploy.rollback_failed": "Rollback fehlgeschlagen! Manuelles Eingreifen nötig.",
    "deploy.health_failed_hint": (
        "Deployment abgeschlossen, aber Health Check fehlgeschlagen. Logs prüfen mit: aegis deploy-logs"
    ),
    "deploy.complete": "Deployment abgeschlossen!",
    "deploy.rolling_starting": "Rolling-Deployment nach {host}...",
    "deploy.rolling_building": "Webserver-Image wird gebaut...",
    "deploy.rolling_pausing": "Worker-Queue wird pausiert...",
    "deploy.rolling_pause_failed": (
        "Pause-Flag konnte nicht gesetzt werden; Worker werden eventuell "
        "mitten im Job per SIGTERM beendet."
    ),
    "deploy.rolling_draining": (
        "Warte bis zu {seconds}s, bis die Worker geleert sind..."
    ),
    "deploy.rolling_drain_timeout": (
        "Worker wurden nicht rechtzeitig geleert. Pause-Flag entfernt; Abbruch."
    ),
    "deploy.rolling_recreating": "Neuerstellung: {services}",
    "deploy.rolling_webserver": (
        "Webserver wird rollend neugestartet "
        "(Warten auf Health-Status, bis zu {seconds}s)..."
    ),
    "deploy.rolling_rollout_failed": (
        "docker rollout ist fehlgeschlagen. Ist das Plugin unter "
        "~/.docker/cli-plugins/ auf dem Deploy-Host installiert?"
    ),
    "deploy.rolling_complete": "Rolling-Deployment abgeschlossen!",
    "deploy.app_running": "   Anwendung läuft unter: http://{host}",
    "deploy.overseer": "   Overseer Dashboard: http://{host}/dashboard/",
    "deploy.view_logs": "   Logs anzeigen: aegis deploy-logs",
    "deploy.check_status": "   Status prüfen: aegis deploy-status",
    "deploy.backup_complete": "Backup abgeschlossen!",
    "deploy.creating_backup_on": "Erstelle Backup auf {host}...",
    "deploy.no_backups": "Keine Backups gefunden.",
    "deploy.backups_header": "Backups auf {host} ({count} gesamt):",
    "deploy.col_timestamp": "Zeitstempel",
    "deploy.col_size": "Größe",
    "deploy.col_database": "Datenbank",
    "deploy.rollback_hint": (
        "Rollback mit: aegis deploy-rollback --backup <timestamp>"
    ),
    "deploy.no_backups_available": "Keine Backups verfügbar.",
    "deploy.rolling_back": "Rollback auf Backup {backup} auf {host}...",
    "deploy.rollback_not_found": "Backup nicht gefunden: {timestamp}",
    "deploy.rollback_stopping": "Stoppe Services...",
    "deploy.rollback_restoring": "Stelle Dateien aus Backup {timestamp} wieder her...",
    "deploy.rollback_restore_failed": "Dateiwiederherstellung fehlgeschlagen: {error}",
    "deploy.rollback_db": "Stelle Datenbank wieder her...",
    "deploy.rollback_db_neon": "Datenbank-Wiederherstellung wird von Neon verwaltet (Branches / Point-in-Time-Restore); lokale Wiederherstellung wird übersprungen",
    "deploy.rollback_pg_wait": "Warte auf PostgreSQL-Bereitschaft...",
    "deploy.rollback_pg_timeout": (
        "PostgreSQL nicht bereit, versuche Wiederherstellung trotzdem"
    ),
    "deploy.rollback_db_failed": "Warnung: Datenbankwiederherstellung fehlgeschlagen",
    "deploy.rollback_starting": "Starte Services...",
    "deploy.rollback_start_failed": "Services konnten nach Rollback nicht gestartet werden",
    "deploy.rollback_complete": "Rollback abgeschlossen!",
    "deploy.rollback_failed_final": "Rollback fehlgeschlagen!",
    "deploy.status_header": "Service-Status auf {host}:",
    "deploy.stop_stopping": "Stoppe Services...",
    "deploy.stop_success": "Services gestoppt",
    "deploy.stop_failed": "Services konnten nicht gestoppt werden",
    "deploy.restart_restarting": "Starte Services neu...",
    "deploy.restart_success": "Services neu gestartet",
    "deploy.restart_failed": "Services konnten nicht neu gestartet werden",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": "Pfad zum Aegis Stack Projekt (Standardwert: aktuelles Verzeichnis)",
    "common.help_project_path": "Pfad zum Projekt (Standardwert: aktuelles Verzeichnis)",
    "common.help_yes": "Bestätigung überspringen",
    "common.help_yes_plural": "Alle Bestätigungen überspringen",
    "common.help_interactive_components": "Komponenten interaktiv wählen",
    "common.help_interactive_services": "Services interaktiv wählen",
    "common.help_force": "Versions-Inkompatibilitätswarnungen erzwingen ignorieren",
    # ── init CLI help ──────────────────────────────────────────────────
    "init.help_arg_name": "Name des neu zu erstellenden Aegis Stack Projekts",
    "init.help_opt_components": "Kommagetrennte Liste von Komponenten (redis,worker,scheduler,database)",
    "init.help_opt_python": "Python-Version für das generierte Projekt (3.11, 3.12, 3.13 oder 3.14)",
    "init.help_opt_force": "Vorhandenes Verzeichnis überschreiben, falls vorhanden",
    "init.help_opt_directory": "Verzeichnis, in dem das Projekt erstellt wird (Standardwert: aktuelles Verzeichnis)",
    "init.help_opt_template_version": "Aus einer bestimmten Template-Version generieren (Tag, Commit oder Branch)",
    "init.help_opt_no_llm_sync": "LLM-Katalog-Synchronisation nach der Projekterstellung überspringen (nur AI-Service)",
    "init.help_opt_dev": "Dev-Modus: Templates aus dem Arbeitsbaum lesen (auch nicht-committed Änderungen)",
    "init.help_opt_services": "Services: {services}. AI-Optionen: ai[framework,backend,providers] mit framework={frameworks}, backend={backends}, providers={providers}",
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": "Kommagetrennte Liste hinzuzufügender Komponenten (scheduler,worker,database)",
    "add.help_opt_scheduler_backend": "Scheduler-Backend: 'memory' (Standard) oder 'sqlite' (aktiviert Persistenz)",
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "Auf eine bestimmte Version aktualisieren (Standardwert: neueste)",
    "update.help_opt_dry_run": "Änderungen nur in der Vorschau anzeigen, ohne sie anzuwenden",
    "update.help_opt_template_path": "Eigenen Template-Pfad anstelle der installierten Version verwenden",
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": "Kommagetrennte Liste zu entfernender Komponenten (scheduler,worker,database)",
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": "Kommagetrennte Liste hinzuzufügender Services (auth,ai)",
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": "Kommagetrennte Liste zu entfernender Services (auth,ai,comms)",
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": "Domainname für das TLS-Zertifikat (z. B. example.com)",
    "ingress.help_opt_email": "E-Mail-Adresse für Let's-Encrypt-Zertifikatsbenachrichtigungen",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "Server-IP-Adresse oder Hostname",
    "deploy.help_opt_user": "SSH-Benutzer für das Deployment",
    "deploy.help_opt_path": "Deployment-Pfad auf dem Server",
    "deploy.help_opt_public_key": "Pfad zu einem öffentlichen Schlüssel, der in die authorized_keys des Deploy-Benutzers eingetragen wird (idempotent). Damit entfällt das manuelle ssh-copy-id vor dem Deployment.",
    "deploy.help_opt_build": "Images vor dem Deployment bauen",
    "deploy.help_opt_backup": "Vor dem Deployment ein Backup erstellen",
    "deploy.help_opt_health": "Nach dem Deployment einen Health-Check ausführen",
    "deploy.help_opt_rolling": (
        "Code-only Deployment ohne HTTP-Downtime. Rollt den Webserver per "
        "docker-rollout und pausiert die Worker-Queue, damit laufende "
        "Jobs sauber abgeschlossen werden. Überspringt DB-Migrationen."
    ),
    "deploy.help_opt_drain_timeout": (
        "Sekunden, die auf das Leeren der Worker gewartet wird, nachdem "
        "die Queue während eines Rolling-Deployments pausiert wurde "
        "(Standard: 90)."
    ),
    "deploy.help_opt_rollout_timeout": (
        "Sekunden, die docker-rollout bei einem Rolling-Deployment auf den "
        "Health-Status des neuen Webservers wartet. Orientiere dich am "
        "HEALTHCHECK-Budget des Containers (start_period + retries × "
        "interval), nicht an einer 60s-Uhr (Standard: 900)."
    ),
    "deploy.help_opt_rollback_backup": "Backup-Zeitstempel, auf den zurückgerollt werden soll (Standardwert: neuestes)",
    "deploy.help_opt_logs_follow": "Logausgabe live mitlesen",
    "deploy.help_opt_logs_service": "Logs nur für einen bestimmten Service anzeigen",
    "deploy.help_opt_shell_service": "Service, mit dem die Verbindung hergestellt wird",
    "deploy.help_opt_gh_repo": "GitHub-Repo als owner/name (Standardwert: automatisch aus git remote origin)",
    "deploy.help_opt_gh_tags": "Deploy-Workflow auch bei Push auf v*-Tags auslösen",
    "deploy.help_opt_gh_overwrite": "Vorhandene GitHub-Secrets und deploy.yml-Workflow überschreiben",
    "deploy.help_opt_dry_run": "Geplante Aktionen anzeigen, ohne Änderungen vorzunehmen",
    "deploy.help_opt_local_key_path": "Pfad, unter dem der generierte private Schlüssel vor dem Aufräumen abgelegt wird. Standardwert: keine lokale Kopie (Schlüssel existiert nur in den GitHub-Secrets).",
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "Installierte Aegis-Plugins prüfen und die Registry durchsuchen",
    "plugins.cannot_read_answers": "{path} konnte nicht gelesen werden: {error}. Kompatibilitätsprüfungen werden übersprungen.",
    "plugins.help_list": "Installierte Plugins und ihre Kompatibilität mit diesem Projekt auflisten.",
    "plugins.help_opt_list_project_path": "Projekt, gegen das die Kompatibilität geprüft wird (standardmäßig das aktuelle Verzeichnis, falls es ein Aegis-Projekt ist).",
    "plugins.help_opt_list_verbose": "Beschreibungs-Spalte anzeigen.",
    "plugins.section_in_tree": "Eingebaut (First-Party)",
    "plugins.section_external": "Externe Plugins",
    "plugins.col_name": "Name",
    "plugins.col_version": "Version",
    "plugins.col_kind": "Art",
    "plugins.col_description": "Beschreibung",
    "plugins.col_status": "Status",
    "plugins.no_external_installed": "Keine externen Plugins installiert. Installation per: pip install aegis-plugin-<name>",
    "plugins.help_info": "Detaillierte Informationen zu einem einzelnen Plugin anzeigen.",
    "plugins.help_arg_info_name": "Plugin-Name (z. B. 'auth', 'scraper')",
    "plugins.help_opt_info_project_path": "Projekt, gegen das die Kompatibilität geprüft wird.",
    "plugins.not_installed_named": "Kein Plugin mit dem Namen '{name}' installiert.",
    "plugins.available_list": "Verfügbar: {names}",
    "plugins.label_first_party": "(First-Party)",
    "plugins.label_verified": "(verifiziert)",
    "plugins.label_unverified": "(Community, nicht verifiziert)",
    "plugins.label_kind": "Art:",
    "plugins.label_type": "Typ:",
    "plugins.label_requires_components": "Benötigt Komp.:",
    "plugins.label_recommends_components": "Empfohlen:",
    "plugins.label_requires_services": "Benötigt Svcs:",
    "plugins.label_requires_plugins": "Benötigt Plug.:",
    "plugins.label_conflicts": "Konflikte:",
    "plugins.label_python_deps": "Python-Deps:",
    "plugins.deps_more": "(+{count} weitere)",
    "plugins.section_options": "Optionen",
    "plugins.option_choices": "Auswahl:",
    "plugins.option_default": "Standard:",
    "plugins.option_auto_requires": "(hat auto_requires)",
    "plugins.info_files": "Dateien: {files}   Migrationen: {migrations} ({tables} Tabellen)   CLI: {cli}",
    "plugins.cli_yes": "ja",
    "plugins.cli_no": "nein",
    "plugins.section_compat": "Kompatibilität",
    "plugins.help_update": "Templates eines installierten Plugins gemäß der aktuell per pip installierten Version neu rendern.",
    "plugins.help_arg_update_name": "Zu aktualisierendes Plugin. Erforderlich, sofern --all nicht angegeben ist.",
    "plugins.help_opt_update_all": "Alle Plugins aktualisieren, die in den _plugins des Projekts eingetragen sind.",
    "plugins.help_opt_update_force": "Update anwenden, auch wenn die aegis_version-Bedingung der neuen Plugin-Version die laufende CLI ausschließt.",
    "plugins.update_need_target": "Bitte Plugin-Namen angeben oder --all verwenden.",
    "plugins.update_either_not_both": "Entweder einen Plugin-Namen ODER --all übergeben, nicht beides.",
    "plugins.update_no_plugins_installed": "In diesem Projekt sind keine Plugins installiert.",
    "plugins.update_not_in_project": "Plugin '{name}' ist in diesem Projekt nicht installiert.",
    "plugins.update_use_list_hint": "Mit `aegis plugins list` ansehen, was verfügbar ist, und mit `aegis add <name>` installieren.",
    "plugins.update_not_pip_installed": "Plugin '{name}' steht in der _plugins-Liste des Projekts, ist aber aktuell nicht per pip installiert; bitte zuerst `pip install aegis-plugin-{name}` ausführen.",
    "plugins.update_already_at": "{name} (bereits auf {version})",
    "plugins.update_forcing": "Update wird trotz Versions-Inkompatibilität erzwungen: {error}",
    "plugins.update_progress": "Plugin wird aktualisiert: {name} ({old} → {new})",
    "plugins.update_confirm_apply": "Update auf '{name}' anwenden?",
    "plugins.update_skipped_by_user": "{name} (vom Benutzer übersprungen)",
    "plugins.update_legacy_strings": "Veraltete String-Einträge in _plugins werden übersprungen: {entries}. Bitte über `aegis add <name>` neu hinzufügen, um auf das aktuelle Dict-Format zu migrieren.",
    "plugins.update_summary_updated": "Aktualisiert: {count}",
    "plugins.update_summary_skipped": "Übersprungen: {count}",
    "plugins.update_summary_failed": "Fehlgeschlagen: {count}",
    "plugins.help_create": "Ein neues aegis-plugin-<name>-Python-Paket gerüstet erzeugen.",
    "plugins.help_arg_create_name": "Plugin-Name (Kleinbuchstaben, keine Bindestriche). Wird zum Python-Paketnamen aegis_plugin_<name> und zum Installationsnamen aegis-plugin-<name>.",
    "plugins.help_opt_create_target": "Übergeordnetes Verzeichnis, in dem das Plugin-Gerüst angelegt wird.",
    "plugins.help_opt_create_author": "Autorenangabe für pyproject.toml und README.",
    "plugins.help_opt_create_description": "Einzeilige Plugin-Beschreibung.",
    "plugins.create_target_missing": "Zielverzeichnis existiert nicht: {target}",
    "plugins.create_already_exists": "Verzeichnis existiert bereits: {output}",
    "plugins.create_pick_different": "Bitte einen anderen Namen wählen oder das vorhandene Verzeichnis entfernen.",
    "plugins.create_starting": "Plugin wird erstellt: {name}",
    "plugins.create_label_target": "Ziel:",
    "plugins.create_label_author": "Autor:",
    "plugins.create_label_description": "Beschreibung:",
    "plugins.create_default_marker": "(Standard)",
    "plugins.create_confirm": "Gerüst erstellen?",
    "plugins.create_cancelled": "Abgebrochen.",
    "plugins.create_success": "{count} Dateien unter {output} erstellt",
    "plugins.create_next_steps_header": "Nächste Schritte:",
    "plugins.create_next_steps_confirm_comment": "prüfen, ob das Plugin erkannt wird",
    "plugins.create_next_steps_edit_comment": "src/aegis_plugin_<name>/plugin.py bearbeiten, um die Verdrahtung zu ergänzen",
    "plugins.help_search": "Die offizielle Plugin-Registry durchsuchen.",
    "plugins.help_arg_search_keyword": "Optionaler Suchbegriff",
    "plugins.search_not_available": "Die Plugin-Registry ist noch nicht verfügbar.",
    "plugins.search_install_hint": "Vorerst: pip install aegis-plugin-<name>, dann aegis plugins list.",
    "plugins.search_future_keyword": "Sobald die Registry online ist, sucht dieser Befehl nach '{keyword}'.",
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "Produktionsreife Python-Apps ab dem ersten Tag.",
    "guided.welcome.body": "Diese geführte Einrichtung führt mit einer kurzen Erklärung durch jeden Baustein, damit Sie entscheiden können, was Ihr Projekt braucht. Wählen Sie jetzt nur, was Sie möchten; alles Übrige lässt sich später mit 'aegis add' hinzufügen.",
    "guided.corestack.title": "IN JEDEM PROJEKT ENTHALTEN",
    "guided.corestack.body": "Jedes Aegis-Projekt beginnt mit diesen beiden – miteinander verbunden und sofort lauffähig.",
    "guided.sidebar.components": "KOMPONENTEN",
    "guided.sidebar.services": "DIENSTE",
    "guided.prompt.worker_backend": "Worker-Backend auswählen",
    "guided.prompt.scheduler_backend": "Scheduler-Persistenz: Job-Verlauf über Neustarts hinweg behalten?",
    "guided.prompt.database_engine": "Datenbank-Engine für {context}",
    "guided.prompt.postgres_provider": "PostgreSQL-Host für {context}",
    "guided.prompt.auth_level": "Authentifizierungsstufe",
    "guided.prompt.ai_framework": "AI-Framework",
    "guided.prompt.ai_providers": "AI-Anbieter: beliebige zum Einbinden auswählen",
    "guided.prompt.ai_storage": "Speicherung von AI-Konversationen",
    "guided.prompt.ai_rag": "RAG hinzufügen: Chat auf Basis Ihrer eigenen Dokumente und Ihres Codes?",
    "guided.prompt.ai_voice": "Sprache hinzufügen: Text-to-Speech und Speech-to-Text?",
    "guided.note.one_datastore": "Ein Datenspeicher pro Projekt: Die hier gewählte Engine legt die Projektdatenbank fest, die alles mitnutzt, was Daten speichert.",
    "guided.note.one_database_host": "Eine Datenbank pro Projekt: Dieser Host bedient alles, was Daten speichert.",
    "guided.multi.hint": "Wählen Sie beliebig viele aus und dann „Weiter“.",
    "guided.choice.add": "Hinzufügen",
    "guided.choice.skip": "Überspringen",
    "guided.screen.add_question": "{name} hinzufügen?",
    "guided.screen.too_small": "Terminal zu klein. Vergrößern Sie auf mindestens {w}x{h}.",
    "guided.review.title": "IHRE KONFIGURATION",
    "guided.review.files_pane": "KOMPONENTENDATEIEN",
    "guided.review.deps_pane": "ABHÄNGIGKEITEN",
    "guided.review.counts": "{files} Komponentendateien · {deps} Abhängigkeiten",
    "guided.building.title": "{name} wird erstellt …",
    "guided.building.preparing": "Wird vorbereitet …",
    "guided.building.note": "Das kann ein bis zwei Minuten dauern; die Hauptarbeit übernimmt uv.",
    "guided.hint.building": "wird erstellt …",
    "guided.done.ready": "{name} ist bereit",
    "guided.done.body": "Projekt generiert und Abhängigkeiten installiert.",
    "guided.done.next_steps": "NÄCHSTE SCHRITTE",
    "guided.done.project_structure": "PROJEKTSTRUKTUR",
    "guided.done.recreate": "DIESEN STACK JEDERZEIT ERNEUT ERSTELLEN",
    "guided.done.copy_note": "Drücken Sie c zum Kopieren; der vollständige Befehl wird nach Abschluss auch unten ausgegeben.",
    "guided.done.copied": "In die Zwischenablage kopiert ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "Weiter",
    "guided.header.label": "geführte Einrichtung",
    "guided.hint.move": "navigieren",
    "guided.hint.select": "auswählen",
    "guided.hint.toggle": "umschalten",
    "guided.hint.back": "zurück",
    "guided.hint.begin": "starten",
    "guided.hint.build": "erstellen",
    "guided.hint.next": "weiter",
    "guided.hint.finish": "fertig",
    "guided.hint.quit": "beenden",
    "guided.hint.services": "zu Diensten springen",
    "guided.hint.copy": "Befehl kopieren",
    "guided.hint.deps": "Abhängigkeiten",
    "guided.hint.files": "Dateien",
    "guided.review.core": "Kern:",
    "guided.review.infrastructure": "Infrastruktur:",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "Dienste:",
    "guided.review.auto": "auto",
    "guided.review.build": "{name} erstellen",
    "guided.review.more": "… +{n} weitere",
    "guided.screen.requires": "Benötigt:",
    "guided.screen.added_automatically": "(automatisch hinzugefügt)",
    "guided.screen.pairs": "Passt gut zu:",
    "guided.screen.docs": "Dokumentation:",
    "component.backend.long": "Eine FastAPI-Anwendung, die Ihre API bereitstellt – von Grund auf asynchron: typisierte Routen, automatische OpenAPI-Dokumentation, Health-Checks und eine Testsuite, die das alles bereits abdeckt.",
    "component.frontend.long": "Ein Flet-Dashboard, das den Systemzustand in Echtzeit und den Status jeder hier gewählten Komponente anzeigt – bereit, mit Ihren eigenen Ansichten erweitert zu werden. Durchgängig Python, keine JavaScript-Build-Kette.",
    "component.worker.long": "Hintergrund-Aufgabenverarbeitung mit wählbarem Backend: arq (Standard), Dramatiq oder TaskIQ. Lagern Sie langsame Arbeit wie E-Mails, Exporte und Drittanbieter-API-Aufrufe aus, damit Anfragen schnell bleiben. Läuft auf Redis, das automatisch hinzugefügt wird.",
    "component.scheduler.long": "Hintergrund-Aufgabenplanung und Cronjobs mit APScheduler. Führen Sie wiederkehrende Arbeit wie Bereinigungen, Berichte und Health-Checks planmäßig aus. Optionale Datenbank-Persistenz bewahrt den Job-Verlauf und übersteht Neustarts.",
    "component.database.long": "Persistenter Speicher mit dem SQLModel-ORM, Alembic-Migrationen und Connection-Pooling. SQLite bietet eine konfigurationsfreie Dateidatenbank für die Entwicklung; PostgreSQL ist der Weg für die Produktion. Die meisten Dienste bauen darauf auf.",
    "component.redis.long": "In-Memory-Datenspeicher, der als Cache und Message-Broker dient. Treibt Hintergrund-Job-Queues und Pub/Sub-Messaging zwischen Ihren Diensten an und gibt Request-Handlern einen schnellen gemeinsamen Cache.",
    "component.ingress.long": "Reverse-Proxy und Traffic-Routing mit Traefik: automatische Service-Erkennung, Schutz von Admin-Endpunkten und optionales TLS über Let's Encrypt. Die Eingangstür für Deployments.",
    "component.observability.long": "Verteiltes Tracing, Metriken und Log-Korrelation mit Pydantic Logfire. Instrumentiert Ihre Anwendung automatisch und passt sich den aktivierten Komponenten an, damit Sie sehen, was die Produktion wirklich tut.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "Vollständige Benutzerverwaltung mit JWT-Authentifizierung, Session-Cookies und Refresh-Token-Rotation. Drei Stufen: einfache E-Mail/Passwort, RBAC-Rollen und -Berechtigungen oder mandantenfähige Organisationen. Enthält Registrierung, Login und einen Admin-Dashboard-Tab.",
    "service.ai.long": "Eine vollständige AI-Plattform: Multi-Provider-Chat, ein LLM-Katalog mit rund 2000 Modellen, Kostenverfolgung mit Nutzungsanalysen, optionales RAG für codebasierte Konversationen und optionale Sprache (TTS/STT). Wählen Sie Pydantic AI oder LangChain als Framework.",
    "service.comms.long": "E-Mail, SMS und Sprachanrufe über etablierte Anbieter: Resend für E-Mail, Twilio für SMS und Sprache. Beide haben kostenlose Kontingente, sodass Sie ohne Kreditkarte starten können.",
    "service.insights.long": "Automatisches Tracking der Verbreitung Ihres Projekts über GitHub, PyPI, Plausible Analytics und Reddit. Erfasst planmäßig, speichert den Verlauf und visualisiert das Wachstum im Dashboard.",
    "service.payment.long": "Zahlungsabwicklung mit Stripe: Checkout-Sessions, Abonnements, Webhooks und Rückerstattungen. Der Testmodus von Stripe braucht keine Kreditkarte, sodass Sie den gesamten Ablauf vor dem Produktivstart aufbauen können.",
    "service.blog.long": "Hauseigenes Markdown-Publishing mit datenbankgestützten Beiträgen, Tags, Entwürfen und einer Editor-Oberfläche im Dashboard. Importieren und exportieren Sie Beiträge als reines Markdown mit Frontmatter.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "In-Memory",
    "guided.choice.scheduler.memory": "Keine Persistenz. Jobs werden bei Neustart zurückgesetzt — im Zweifel überspringen.",
    "guided.choice.scheduler.sqlite": "Job-Verlauf in einer Dateidatenbank speichern.",
    "guided.choice.scheduler.postgres": "Job-Verlauf speichern, produktionstauglich.",
    "guided.choice.worker.arq": "Einfacher, gut getesteter asynchroner Worker mit minimaler Konfiguration. Ideal für I/O-lastige Aufgaben. Der Standard.",
    "guided.choice.worker.dramatiq": "Mehrprozess-Aktormodell. Ideal für CPU-lastige Aufgaben, die von mehreren OS-Prozessen profitieren.",
    "guided.choice.worker.taskiq": "Async-nativ mit Brokern pro Queue und Redis-Streams-Transport mit Bestätigungen.",
    "guided.choice.db.sqlite": "Konfigurationsfreie Dateidatenbank. Ideal für die Entwicklung.",
    "guided.choice.db.postgres": "Produktionstauglich mit Connection-Pooling.",
    "guided.choice.db_provider.container": "Lokaler postgres:16-Container, Dev und Prod.",
    "guided.choice.db_provider.neon": (
        "Serverloses Postgres: Cloud in Prod, lokaler Container in Dev."
    ),
    "guided.choice.auth.basic": "E-Mail und Passwort mit JWT-Sitzungen.",
    "guided.choice.auth.rbac": "Fügt Rollen und Berechtigungen hinzu.",
    "guided.choice.auth.org": "Mandantenfähige Organisationen.",
    "guided.choice.framework.pydantic_ai": "Typisiert und leichtgewichtig. Der Standard.",
    "guided.choice.framework.langchain": "Großes Ökosystem, viele Integrationen.",
    "guided.choice.storage.memory": "Kein Verlauf, nichts einzurichten.",
    "guided.choice.storage.sqlite": "Dauerhafter Chat-Verlauf in einer Dateidatenbank.",
    "guided.choice.storage.postgres": "Dauerhaft und produktionstauglich.",
    "guided.choice.provider.public.desc": "Kostenloser öffentlicher Endpunkt",
    "guided.choice.provider.public.pricing": "Kostenlos, kein API-Schlüssel",
    "guided.choice.provider.openai.desc": "GPT-Modelle",
    "guided.choice.provider.openai.pricing": "Kostenpflichtig",
    "guided.choice.provider.anthropic.desc": "Claude-Modelle",
    "guided.choice.provider.anthropic.pricing": "Kostenpflichtig",
    "guided.choice.provider.google.desc": "Gemini-Modelle",
    "guided.choice.provider.google.pricing": "Kostenloses Kontingent (nur Flash)",
    "guided.choice.provider.groq.desc": "Schnelle Inferenz",
    "guided.choice.provider.groq.pricing": "Kostenloses Kontingent",
    "guided.choice.provider.mistral.desc": "Offene Modelle",
    "guided.choice.provider.mistral.pricing": "Überwiegend kostenpflichtig",
    "guided.choice.provider.cohere.desc": "Enterprise-Fokus",
    "guided.choice.provider.cohere.pricing": "Eingeschränkt kostenlos",
    "guided.choice.provider.ollama.desc": "Lokale Inferenz",
    "guided.choice.provider.ollama.pricing": "Kostenlos (lokal)",
    "build.step.render": "Projektdateien werden erstellt",
    "build.step.deps": "Abhängigkeiten werden installiert",
    "build.step.env": "Umgebungskonfiguration",
    "build.step.migrate": "Migrationen werden angewendet",
    "build.step.llm": "LLM-Katalog wird synchronisiert",
    "build.step.format": "Code wird formatiert",
}
