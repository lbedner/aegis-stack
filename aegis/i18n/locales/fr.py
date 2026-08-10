"""French locale — Définitions des messages en français."""

MESSAGES: dict[str, str] = {
    # ── Validation ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "Nom de projet invalide. Seuls les lettres, chiffres, tirets "
        "et underscores sont autorisés."
    ),
    "validation.reserved_name": "« {name} » est un nom réservé.",
    "validation.name_too_long": ("Nom de projet trop long. Maximum 50 caractères."),
    "validation.invalid_python": (
        "Version Python invalide « {version} ». Doit être l'une de : {supported}"
    ),
    "validation.unknown_service": "Service inconnu : {name}",
    "validation.unknown_services": "Services inconnus : {names}",
    "validation.unknown_component": "Composant inconnu : {name}",
    # ── Init command ───────────────────────────────────────────────────
    "init.title": "Initialisation du projet Aegis Stack",
    "init.location": "Emplacement :",
    "init.template_version": "Version du modèle :",
    "init.dir_exists": "Le répertoire « {path} » existe déjà",
    "init.dir_exists_hint": "Utilisez --force pour écraser ou choisissez un autre nom",
    "init.overwriting": "Écrasement du répertoire existant : {path}",
    "init.services_require": "Les services nécessitent les composants : {components}",
    "init.compat_errors": "Erreurs de compatibilité service-composant :",
    "init.suggestion_add": (
        "Suggestion : ajoutez les composants manquants --components {components}"
    ),
    "init.suggestion_remove": (
        "Ou retirez --components pour laisser les services ajouter leurs dépendances automatiquement."
    ),
    "init.suggestion_interactive": (
        "Vous pouvez aussi utiliser le mode interactif pour ajouter les dépendances automatiquement."
    ),
    "init.auto_detected_scheduler": (
        "Détecté automatiquement : Scheduler avec persistance {backend}"
    ),
    "init.auto_added_deps": "Dépendances ajoutées automatiquement : {deps}",
    "init.auto_added_by_services": "Ajouté automatiquement par les services :",
    "init.required_by": "requis par {services}",
    "init.config_title": "Configuration du projet",
    "init.config_name": "Nom :",
    "init.config_core": "Base :",
    "init.config_infra": "Infrastructure :",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "Services :",
    "init.component_files": "Fichiers des composants :",
    "init.entrypoints": "Points d'entrée :",
    "init.worker_queues": "Files d'attente du worker :",
    "init.dependencies": "Dépendances à installer :",
    "init.confirm_create": "Créer ce projet ?",
    "init.cancelled": "Création du projet annulée",
    "init.removing_dir": "Suppression du répertoire existant : {path}",
    "init.creating": "Création du projet : {name}",
    "init.error": "Erreur lors de la création du projet : {error}",
    "init.replay_hint": "Recréez cette configuration à tout moment :",
    # ── Interactive: section headers ───────────────────────────────────
    "interactive.component_selection": "Sélection des composants",
    "interactive.service_selection": "Sélection des services",
    "interactive.core_included": (
        "Composants de base ({components}) inclus automatiquement"
    ),
    "interactive.infra_header": "Composants d'infrastructure :",
    "interactive.services_intro": (
        "Les services fournissent la logique métier de votre application."
    ),
    # ── Component descriptions ──────────────────────────────────────────
    "component.backend": "Serveur backend FastAPI",
    "component.frontend": "Interface frontend Flet",
    "component.redis": "Cache Redis et courtier de messages",
    "component.worker": "Traitement de tâches en arrière-plan (arq, Dramatiq ou TaskIQ)",
    "component.scheduler": "Infrastructure de planification de tâches",
    "component.database": "Base de données avec ORM SQLModel (SQLite ou PostgreSQL)",
    "component.ingress": "Reverse proxy et répartiteur de charge Traefik",
    "component.observability": "Observabilité, traçage et métriques Logfire",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Service descriptions ────────────────────────────────────────────
    "service.auth": "Authentification et autorisation avec jetons JWT",
    "service.ai": "Service de chatbot IA avec support multi-framework",
    "service.comms": "Service de communications : e-mail, SMS et voix",
    "service.blog": "Blog Markdown avec brouillons, publication et tags",
    # ── Interactive: component prompts ─────────────────────────────────
    "interactive.add_prompt": "Ajouter {description} ?",
    "interactive.add_with_redis": "Ajouter {description} ? (Redis sera ajouté automatiquement)",
    "interactive.worker_configured": "Worker configuré avec le backend {backend}",
    # ── Interactive: scheduler ─────────────────────────────────────────
    "interactive.scheduler_persistence": "Persistance du scheduler :",
    "interactive.persist_prompt": (
        "Voulez-vous persister les tâches planifiées ? "
        "(Active l'historique et la reprise après redémarrage)"
    ),
    "interactive.scheduler_db_configured": "Scheduler + base de données {engine} configurés",
    "interactive.bonus_backup": "Bonus : ajout d'une tâche de sauvegarde de la base de données",
    "interactive.backup_desc": (
        "Sauvegarde quotidienne de la base de données incluse (exécution à 2h du matin)"
    ),
    # ── Interactive: database engine ───────────────────────────────────
    "interactive.db_engine_label": "Moteur de base de données {context} :",
    "interactive.db_select": "Sélectionnez le moteur de base de données :",
    "interactive.db_sqlite": "SQLite - Simple, fichier local (adapté au développement)",
    "interactive.db_postgres": ("PostgreSQL - Production, support multi-conteneur"),
    "interactive.db_reuse": "Base de données déjà sélectionnée : {engine}",
    "interactive.db_provider_select": "Choisissez l'hôte PostgreSQL :",
    "interactive.db_provider_container": (
        "Conteneur local - postgres:16 sous Docker (dev et prod)"
    ),
    "interactive.db_provider_neon": (
        "Neon - Postgres serverless (cloud en prod, conteneur local en dev)"
    ),
    # ── Interactive: worker backend ────────────────────────────────────
    "interactive.worker_label": "Backend du worker :",
    "interactive.worker_select": "Sélectionnez le backend du worker :",
    "interactive.worker_arq": "arq - Async, léger (par défaut)",
    "interactive.worker_dramatiq": (
        "Dramatiq - Multi-processus, idéal pour le calcul intensif"
    ),
    "interactive.worker_taskiq": (
        "TaskIQ - Async, style framework avec brokers par file"
    ),
    # ── Interactive: auth ──────────────────────────────────────────────
    "interactive.auth_header": "Services d'authentification :",
    "interactive.auth_level_label": "Niveau d'authentification :",
    "interactive.auth_select": "Quel type d'authentification ?",
    "interactive.auth_basic": "Basique - Connexion e-mail/mot de passe",
    "interactive.auth_rbac": "Avec rôles - + contrôle d'accès par rôle (expérimental)",
    "interactive.auth_org": "Avec organisations - + support multi-tenant (expérimental)",
    "interactive.auth_selected": "Niveau d'authentification sélectionné : {level}",
    "interactive.auth_db_required": "Base de données requise :",
    "interactive.auth_db_reason": (
        "L'authentification nécessite une base de données pour le stockage des utilisateurs"
    ),
    "interactive.auth_db_details": "(comptes utilisateurs, sessions, jetons JWT)",
    "interactive.auth_db_already": "Composant base de données déjà sélectionné",
    "interactive.auth_db_confirm": "Continuer et ajouter le composant base de données ?",
    "interactive.auth_cancelled": "Service d'authentification annulé",
    "interactive.auth_db_configured": "Authentification + base de données configurées",
    # ── Interactive: AI service ────────────────────────────────────────
    "interactive.ai_header": "Services IA et Machine Learning :",
    "interactive.ai_framework_label": "Sélection du framework IA :",
    "interactive.ai_framework_intro": "Choisissez votre framework IA :",
    "interactive.ai_pydanticai": (
        "PydanticAI - Framework IA typé et Pythonic (recommandé)"
    ),
    "interactive.ai_langchain": (
        "LangChain - Framework populaire avec intégrations étendues"
    ),
    "interactive.ai_use_pydanticai": "Utiliser PydanticAI ? (recommandé)",
    "interactive.ai_selected_framework": "Framework sélectionné : {framework}",
    "interactive.ai_tracking_context": "Suivi de l'utilisation IA",
    "interactive.ai_tracking_label": "Suivi d'utilisation LLM :",
    "interactive.ai_tracking_prompt": (
        "Activer le suivi d'utilisation ? (comptage de tokens, coûts, historique des conversations)"
    ),
    "interactive.ai_sync_label": "Synchronisation du catalogue LLM :",
    "interactive.ai_sync_desc": (
        "La synchronisation récupère les dernières données depuis les API OpenRouter/LiteLLM"
    ),
    "interactive.ai_sync_time": (
        "Nécessite un accès réseau et prend environ 30 à 60 secondes"
    ),
    "interactive.ai_sync_prompt": "Synchroniser le catalogue LLM pendant la génération du projet ?",
    "interactive.ai_sync_will": "Le catalogue LLM sera synchronisé après la génération du projet",
    "interactive.ai_sync_skipped": (
        "Synchronisation LLM ignorée - des données de fixtures statiques seront disponibles"
    ),
    "interactive.ai_provider_label": "Sélection du fournisseur IA :",
    "interactive.ai_provider_intro": (
        "Choisissez les fournisseurs IA à inclure (sélection multiple possible)"
    ),
    "interactive.ai_provider_options": "Options de fournisseurs :",
    "interactive.ai_provider_recommended": "(Recommandé)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI - Modèles GPT (Payant)",
    "interactive.ai_provider.anthropic": "Anthropic - Modèles Claude (Payant)",
    "interactive.ai_provider.google": "Google - Modèles Gemini (Offre gratuite)",
    "interactive.ai_provider.groq": "Groq - Inférence rapide (Offre gratuite)",
    "interactive.ai_provider.mistral": "Mistral - Modèles ouverts (Majoritairement payant)",
    "interactive.ai_provider.cohere": "Cohere - Orienté entreprise (Gratuit limité)",
    "interactive.ai_provider.ollama": "Ollama - Inférence locale (Gratuit)",
    "interactive.ai_no_providers": (
        "Aucun fournisseur sélectionné, ajout des valeurs par défaut recommandées..."
    ),
    "interactive.ai_selected_providers": "Fournisseurs sélectionnés : {providers}",
    "interactive.ai_deps_optimized": (
        "Les dépendances seront optimisées selon votre sélection"
    ),
    "interactive.ai_ollama_label": "Mode de déploiement Ollama :",
    "interactive.ai_ollama_intro": "Comment voulez-vous exécuter Ollama ?",
    "interactive.ai_ollama_host": (
        "Hôte - Connexion à Ollama sur votre machine (Mac/Windows)"
    ),
    "interactive.ai_ollama_docker": (
        "Docker - Exécuter Ollama dans un conteneur Docker (Linux/Déploiement)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "Se connecter à Ollama sur l'hôte ? (recommandé pour Mac/Windows)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama se connectera à host.docker.internal:11434"
    ),
    "interactive.ai_ollama_host_hint": "Assurez-vous qu'Ollama est en cours d'exécution : ollama serve",
    "interactive.ai_ollama_docker_ok": (
        "Le service Ollama sera ajouté à docker-compose.yml"
    ),
    "interactive.ai_ollama_docker_hint": (
        "Note : le premier démarrage peut prendre du temps pour télécharger les modèles"
    ),
    "interactive.ai_rag_label": "RAG (Retrieval-Augmented Generation) :",
    "interactive.ai_rag_prompt": (
        "Activer RAG pour l'indexation de documents et la recherche sémantique ?"
    ),
    "interactive.ai_rag_enabled": "RAG activé avec le vector store ChromaDB",
    "interactive.ai_voice_label": "Voix (Text-to-Speech et Speech-to-Text) :",
    "interactive.ai_voice_prompt": (
        "Activer les fonctionnalités vocales ? (TTS et STT pour les interactions vocales)"
    ),
    "interactive.ai_voice_enabled": "Voix activée avec support TTS et STT",
    "interactive.ai_db_already": "Base de données déjà sélectionnée - suivi d'utilisation activé",
    "interactive.ai_db_added": "Base de données ({backend}) ajoutée pour le suivi d'utilisation",
    "interactive.ai_configured": "Service IA configuré",
    # ── Shared: validation ──────────────────────────────────────────────
    "shared.not_copier_project": "Le projet dans {path} n'a pas été généré avec Copier.",
    "shared.copier_only": (
        "La commande « aegis {command} » ne fonctionne qu'avec les projets générés par Copier."
    ),
    "shared.regenerate_hint": (
        "Pour ajouter des composants, regénérez le projet avec les nouveaux composants inclus."
    ),
    "shared.git_not_initialized": "Le projet n'est pas dans un dépôt git",
    "shared.git_required": "Les mises à jour Copier nécessitent git pour le suivi des modifications",
    "shared.git_init_hint": (
        "Les projets créés avec « aegis init » devraient avoir git initialisé automatiquement"
    ),
    "shared.git_manual_init": (
        "Si vous avez créé ce projet manuellement, exécutez : "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "Un nom de composant vide n'est pas autorisé",
    "shared.empty_service": "Un nom de service vide n'est pas autorisé",
    # ── Shared: next steps / review ──────────────────────────────────
    "shared.next_steps": "Prochaines étapes :",
    "shared.next_make_check": "   1. Exécutez « make check » pour vérifier la mise à jour",
    "shared.next_test": "   2. Testez votre application",
    "shared.next_commit": "   3. Validez les modifications avec : git add . && git commit",
    "shared.review_header": "Examiner les modifications :",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "Opération annulée",
    "shared.interactive_ignores_args": (
        "Attention : le flag --interactive ignore les arguments de composants"
    ),
    "shared.no_components_selected": "Aucun composant sélectionné",
    "shared.no_services_selected": "Aucun service sélectionné",
    # ── Add command ──────────────────────────────────────────────────
    "add.title": "Aegis Stack - Ajout de composants",
    "add.project": "Projet : {path}",
    "add.error_no_args": (
        "Erreur : l'argument components est requis (ou utilisez --interactive)"
    ),
    "add.usage_hint": "Utilisation : aegis add scheduler,worker",
    "add.interactive_hint": "Ou : aegis add --interactive",
    "add.auto_added_deps": "Dépendances ajoutées automatiquement : {deps}",
    "add.validation_failed": "Validation des composants échouée : {error}",
    "add.load_config_failed": "Impossible de charger la configuration du projet : {error}",
    "add.already_enabled": "Déjà activé : {components}",
    "add.all_enabled": "Tous les composants demandés sont déjà activés !",
    "add.components_to_add": "Composants à ajouter :",
    "add.scheduler_backend": "Backend du scheduler : {backend}",
    "add.confirm": "Ajouter ces composants ?",
    "add.updating": "Mise à jour du projet...",
    "add.adding": "Ajout de {component}...",
    "add.added_files": "{count} fichiers ajoutés",
    "add.skipped_files": "{count} fichiers existants ignorés",
    "add.success": "Composants ajoutés !",
    "add.failed_component": "Échec de l'ajout de {component} : {error}",
    "add.failed": "Échec de l'ajout des composants : {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "Format de composant invalide : {error}",
    "add.bracket_override": (
        "La syntaxe entre crochets « scheduler[{engine}] » remplace --backend {backend}"
    ),
    "add.invalid_scheduler_backend": "Backend de scheduler invalide : « {backend} »",
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "Options valides : {options}",
    "add.postgres_coming": "Note : le support PostgreSQL arrive dans une prochaine version",
    "add.auto_added_db": "Composant base de données ajouté automatiquement pour la persistance du scheduler",
    "add.generated_migration": "Migration générée : {name}",
    "add.scheduler_db_engine_mismatch": "Impossible d'utiliser le backend de scheduler '{backend}' : le moteur de base de données du projet est '{engine}'. Ils doivent correspondre.",
    # ── Remove command ────────────────────────────────────────────────
    "remove.title": "Aegis Stack - Suppression de composants",
    "remove.project": "Projet : {path}",
    "remove.error_no_args": (
        "Erreur : l'argument components est requis (ou utilisez --interactive)"
    ),
    "remove.usage_hint": "Utilisation : aegis remove scheduler,worker",
    "remove.interactive_hint": "Ou : aegis remove --interactive",
    "remove.no_selected": "Aucun composant sélectionné pour la suppression",
    "remove.validation_failed": "Validation des composants échouée : {error}",
    "remove.load_config_failed": "Impossible de charger la configuration du projet : {error}",
    "remove.cannot_remove_core": "Impossible de supprimer le composant de base : {component}",
    "remove.not_enabled": "Non activé : {components}",
    "remove.nothing_to_remove": "Aucun composant à supprimer !",
    "remove.auto_remove_redis": (
        "Suppression automatique de Redis (pas de fonctionnalité autonome, utilisé uniquement par le worker)"
    ),
    "remove.scheduler_persistence_warn": "IMPORTANT : avertissement de persistance du scheduler",
    "remove.scheduler_persistence_detail": (
        "Votre scheduler utilise SQLite pour la persistance des tâches."
    ),
    "remove.scheduler_db_remains": (
        "Le fichier de base de données data/scheduler.db sera conservé."
    ),
    "remove.scheduler_keep_hint": (
        "Pour conserver l'historique : laissez le composant base de données"
    ),
    "remove.scheduler_remove_hint": (
        "Pour tout supprimer : supprimez aussi le composant base de données"
    ),
    "remove.components_to_remove": "Composants à supprimer :",
    "remove.warning_delete": (
        "ATTENTION : les fichiers des composants seront SUPPRIMÉS de votre projet !"
    ),
    "remove.commit_hint": "Assurez-vous d'avoir validé vos modifications dans git.",
    "remove.confirm": "Supprimer ces composants ?",
    "remove.removing_all": "Suppression des composants...",
    "remove.removing": "Suppression de {component}...",
    "remove.removed_files": "{count} fichiers supprimés",
    "remove.failed_component": "Échec de la suppression de {component} : {error}",
    "remove.success": "Composants supprimés !",
    "remove.failed": "Échec de la suppression des composants : {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Manual updater ─────────────────────────────────────────────────
    "updater.processing_files": "Traitement de {count} fichiers de composants...",
    "updater.updating_shared": "Mise à jour des fichiers de modèle partagés...",
    "updater.shared_preserved": "Modifications locales conservées (régénération ignorée, fusionnez manuellement) : {file}",
    "updater.shared_merged": "Modifications du modèle fusionnées dans votre fichier personnalisé : {file}",
    "updater.shared_conflict": "Conflit de fusion (marqueurs écrits, résolvez manuellement) : {file}",
    "updater.running_postgen": "Exécution des tâches post-génération...",
    "updater.deps_synced": "Dépendances synchronisées (uv sync)",
    "updater.code_formatted": "Code formaté (make fix)",
    # ── Project map ──────────────────────────────────────────────────
    "projectmap.new": "NOUVEAU",
    # ── Post-generation: setup tasks ──────────────────────────────────
    "postgen.setup_start": "Configuration de l'environnement du projet...",
    "postgen.deps_installing": "Installation des dépendances avec uv...",
    "postgen.deps_success": "Dépendances installées",
    "postgen.deps_failed": "Échec de la génération du projet : l'installation des dépendances a échoué",
    "postgen.deps_failed_detail": (
        "Les fichiers du projet sont en place, mais le projet n'est pas utilisable."
    ),
    "postgen.deps_failed_hint": (
        "Corrigez le problème de dépendances (vérifiez la compatibilité Python) et réessayez."
    ),
    "postgen.deps_warn_failed": "Attention : l'installation des dépendances a échoué",
    "postgen.deps_manual": "Exécutez « uv sync » manuellement après la création du projet",
    "postgen.deps_timeout": (
        "Attention : délai d'installation des dépendances dépassé - exécutez « uv sync » manuellement"
    ),
    "postgen.deps_uv_missing": "Attention : uv introuvable dans le PATH",
    "postgen.deps_uv_install": "Installez d'abord uv : https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "Attention : l'installation des dépendances a échoué : {error}",
    "postgen.env_setup": "Configuration de l'environnement...",
    "postgen.env_created": "Fichier d'environnement créé depuis .env.example",
    "postgen.env_exists": "Le fichier d'environnement existe déjà",
    "postgen.env_missing": "Attention : fichier .env.example introuvable",
    "postgen.env_error": "Attention : la configuration de l'environnement a échoué : {error}",
    "postgen.env_manual": "Copiez .env.example vers .env manuellement",
    # ── Post-generation: database/migrations ────────────────────────────
    "postgen.db_setup": "Configuration du schéma de la base de données...",
    "postgen.db_success": "Tables de la base de données créées",
    "postgen.db_alembic_missing": "Attention : fichier de configuration Alembic introuvable à {path}",
    "postgen.db_alembic_hint": (
        "Migration de la base de données ignorée. Vérifiez que le fichier de configuration "
        "existe et exécutez « alembic upgrade head » manuellement."
    ),
    "postgen.db_failed": "Attention : la configuration des migrations a échoué",
    "postgen.db_manual": "Exécutez « alembic upgrade head » manuellement après la création du projet",
    "postgen.db_timeout": (
        "Attention : délai de configuration des migrations dépassé - exécutez « alembic upgrade head » manuellement"
    ),
    "postgen.db_error": "Attention : la configuration des migrations a échoué : {error}",
    # ── Post-generation: LLM fixtures/sync ────────────────────────────
    "postgen.llm_seeding": "Chargement des fixtures LLM...",
    "postgen.llm_seed_success": "Fixtures LLM chargées",
    "postgen.llm_seed_failed": "Attention : le chargement des fixtures LLM a échoué",
    "postgen.llm_seed_manual": (
        "Vous pouvez charger les fixtures manuellement en exécutant le chargeur de fixtures"
    ),
    "postgen.llm_seed_timeout": "Attention : délai de chargement des fixtures LLM dépassé",
    "postgen.llm_seed_error": "Attention : le chargement des fixtures LLM a échoué : {error}",
    "postgen.llm_syncing": "Synchronisation du catalogue LLM depuis les API externes...",
    "postgen.llm_sync_success": "Catalogue LLM synchronisé",
    "postgen.llm_sync_failed": "Attention : la synchronisation du catalogue LLM a échoué",
    "postgen.llm_sync_manual": (
        "Exécutez « {slug} llm sync » manuellement pour alimenter le catalogue"
    ),
    "postgen.llm_sync_timeout": "Attention : délai de synchronisation du catalogue LLM dépassé",
    "postgen.llm_sync_error": "Attention : la synchronisation du catalogue LLM a échoué : {error}",
    # ── Post-generation: formatting ───────────────────────────────────
    "postgen.format_timeout": (
        "Attention : délai de formatage dépassé - exécutez « make fix » manuellement"
    ),
    "postgen.format_error": "Attention : formatage automatique ignoré : {error}",
    "postgen.format_error_manual": "Exécutez « make fix » manuellement pour formater le code",
    "postgen.format_start": "Formatage automatique du code généré...",
    "postgen.format_success": "Formatage du code terminé",
    "postgen.format_partial": (
        "Quelques problèmes de formatage détectés, mais le projet créé"
    ),
    "postgen.format_manual": "Exécutez « make fix » manuellement pour résoudre les problèmes restants",
    "postgen.format_hint": "Exécutez « make fix » pour formater le code",
    "postgen.llm_sync_skipped": "Synchronisation du catalogue LLM ignorée",
    "postgen.llm_fixtures_outdated": "Données de fixtures statiques chargées (potentiellement obsolètes)",
    "postgen.llm_sync_hint": "Exécutez « {slug} llm sync » plus tard pour obtenir les dernières données",
    "postgen.llm_fixtures_fallback": (
        "Les données de fixtures statiques sont disponibles mais potentiellement obsolètes"
    ),
    "postgen.ready": "Projet prêt à être lancé !",
    "postgen.next_steps": "Prochaines étapes :",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Ouvrir Overseer : http://localhost:8000/dashboard/",
    # ── Post-generation: project map ──────────────────────────────────
    "projectmap.title": "Structure du projet :",
    "projectmap.components": "Composants",
    "projectmap.services": "Logique métier",
    "projectmap.models": "Modèles de base de données",
    "projectmap.cli": "Commandes CLI",
    "projectmap.entrypoints": "Points d'exécution",
    "projectmap.tests": "Suite de tests",
    "projectmap.migrations": "Migrations",
    "projectmap.auth": "Authentification",
    "projectmap.ai": "Conversations IA",
    "projectmap.comms": "Communications",
    "projectmap.insights": "Adoption metrics",
    "projectmap.payment": "Payments and subscriptions",
    "projectmap.blog": "Markdown blog",
    "projectmap.finance": "Personal finance",
    "projectmap.docs": "Documentation",
    # ── Post-generation: footer ───────────────────────────────────────
    "postgen.docs_link": "Docs : https://docs.aegis-stack.io",
    "postgen.star_prompt": (
        "Si Aegis Stack vous a simplifié la vie, pensez à laisser une étoile :"
    ),
    # ── Add-service command ────────────────────────────────────────────
    "add_service.title": "Aegis Stack - Ajout de services",
    "add_service.project": "Projet : {path}",
    "add_service.error_no_args": (
        "Erreur : l'argument services est requis (ou utilisez --interactive)"
    ),
    "add_service.usage_hint": "Utilisation : aegis add-service auth,ai",
    "add_service.interactive_hint": "Ou : aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "Attention : le flag --interactive ignore les arguments de services"
    ),
    "add_service.no_selected": "Aucun service sélectionné",
    "add_service.already_enabled": "Déjà activé : {services}",
    "add_service.all_enabled": "Tous les services demandés sont déjà activés !",
    "add_service.validation_failed": "Validation des services échouée : {error}",
    "add_service.load_config_failed": "Impossible de charger la configuration du projet : {error}",
    "add_service.services_to_add": "Services à ajouter :",
    "add_service.required_components": "Composants requis (seront ajoutés automatiquement) :",
    "add_service.already_have_components": (
        "Composants requis déjà présents : {components}"
    ),
    "add_service.confirm": "Ajouter ces services ?",
    "add_service.adding_component": "Ajout du composant requis : {component}...",
    "add_service.failed_component": "Échec de l'ajout du composant {component} : {error}",
    "add_service.added_files": "{count} fichiers ajoutés",
    "add_service.skipped_files": "{count} fichiers existants ignorés",
    "add_service.preserved_files": "{count} fichier(s) partagé(s) nécessitent une révision manuelle (voir les messages ci-dessus)",
    "add_service.adding_service": "Ajout du service : {service}...",
    "add_service.failed_service": "Échec de l'ajout du service {service} : {error}",
    "add_service.resolve_failed": "Échec de la résolution des dépendances de services : {error}",
    "add_service.bootstrap_alembic": "Initialisation de l'infrastructure Alembic...",
    "add_service.created_file": "Créé : {file}",
    "add_service.generated_migration": "Migration générée : {name}",
    "add_service.applying_migrations": "Application des migrations de base de données...",
    "add_service.migration_failed": (
        "Attention : la migration automatique a échoué. Exécutez « make migrate » manuellement."
    ),
    "add_service.success": "Services ajoutés !",
    "add_service.failed": "Échec de l'ajout des services : {error}",
    "add_service.auth_setup": "Configuration du service Auth :",
    "add_service.auth_create_users": "   1. Créer des utilisateurs de test : {cmd}",
    "add_service.auth_view_routes": "   2. Voir les routes d'authentification : {url}",
    "add_service.ai_setup": "Configuration du service IA :",
    "add_service.ai_set_provider": (
        "   1. Définir {env_var} dans .env (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": "   2. Définir la clé API du fournisseur ({env_var}, etc.)",
    "add_service.ai_test_cli": "   3. Tester avec le CLI : {cmd}",
    # ── Remove-service command ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack - Suppression de services",
    "remove_service.project": "Projet : {path}",
    "remove_service.error_no_args": (
        "Erreur : l'argument services est requis (ou utilisez --interactive)"
    ),
    "remove_service.usage_hint": "Utilisation : aegis remove-service auth,ai",
    "remove_service.interactive_hint": "Ou : aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "Attention : le flag --interactive ignore les arguments de services"
    ),
    "remove_service.no_selected": "Aucun service sélectionné pour la suppression",
    "remove_service.not_enabled": "Non activé : {services}",
    "remove_service.nothing_to_remove": "Aucun service à supprimer !",
    "remove_service.validation_failed": "Validation des services échouée : {error}",
    "remove_service.load_config_failed": (
        "Impossible de charger la configuration du projet : {error}"
    ),
    "remove_service.services_to_remove": "Services à supprimer :",
    "remove_service.auth_warning": "IMPORTANT : avertissement concernant le service Auth",
    "remove_service.auth_delete_intro": "La suppression du service Auth entraînera la suppression de :",
    "remove_service.auth_delete_endpoints": "Points d'accès API d'authentification",
    "remove_service.auth_delete_models": "Modèle utilisateur et services d'authentification",
    "remove_service.auth_delete_jwt": "Code de gestion des jetons JWT",
    "remove_service.auth_db_note": (
        "Note : les tables de base de données et les migrations Alembic ne sont PAS supprimées."
    ),
    "remove_service.warning_delete": (
        "ATTENTION : les fichiers de services seront SUPPRIMÉS de votre projet !"
    ),
    "remove_service.confirm": "Supprimer ces services ?",
    "remove_service.removing": "Suppression du service : {service}...",
    "remove_service.failed_service": "Échec de la suppression du service {service} : {error}",
    "remove_service.removed_files": "{count} fichiers supprimés",
    "remove_service.success": "Services supprimés !",
    "remove_service.failed": "Échec de la suppression des services : {error}",
    "remove_service.deps_not_removed": (
        "Note : les dépendances de services (base de données, etc.) n'ont PAS été supprimées."
    ),
    "remove_service.deps_remove_hint": (
        "Utilisez « aegis remove <composant> » pour supprimer les composants séparément."
    ),
    # ── Version command ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Components command ─────────────────────────────────────────────
    "components.core_title": "COMPOSANTS DE BASE",
    "components.backend_desc": (
        "  backend      - Serveur backend FastAPI (toujours inclus)"
    ),
    "components.frontend_desc": (
        "  frontend     - Interface frontend Flet (toujours inclus)"
    ),
    "components.infra_title": "COMPOSANTS D'INFRASTRUCTURE",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "Requis : {deps}",
    "components.recommends": "Recommandé : {deps}",
    "components.usage_hint": (
        "Utilisez « aegis init NOM_PROJET --components redis,worker » pour sélectionner les composants"
    ),
    # ── Services command ───────────────────────────────────────────────
    "services.title": "SERVICES DISPONIBLES",
    "services.type_auth": "Services d'authentification",
    "services.type_payment": "Services de paiement",
    "services.type_ai": "Services IA et Machine Learning",
    "services.type_notification": "Services de notification",
    "services.type_analytics": "Services d'analyse",
    "services.type_storage": "Services de stockage",
    "services.type_content": "Services de contenu",
    "services.type_finance": "Services de finance",
    "services.requires_components": "Composants requis : {deps}",
    "services.recommends_components": "Composants recommandés : {deps}",
    "services.requires_services": "Services requis : {deps}",
    "services.none_available": "  Aucun service disponible pour le moment.",
    "services.usage_hint": (
        "Utilisez « aegis init NOM_PROJET --services auth » pour ajouter des services"
    ),
    # ── Update command ─────────────────────────────────────────────────
    "update.title": "Aegis Stack - Mise à jour du modèle",
    "update.not_copier": "Le projet dans {path} n'a pas été généré avec Copier.",
    "update.copier_only": (
        "La commande « aegis update » ne fonctionne qu'avec les projets générés par Copier."
    ),
    "update.need_regen": "Les projets générés avant la v0.2.0 doivent être regénérés.",
    "update.project": "Projet : {path}",
    "update.commit_or_stash": (
        "Validez ou remisez vos modifications avant d'exécuter « aegis update »."
    ),
    "update.clean_required": (
        "Copier nécessite un arbre git propre pour fusionner les modifications en toute sécurité."
    ),
    "update.git_clean": "Arbre git propre",
    "update.dirty_tree": "L'arbre git contient des modifications non validées",
    "update.changelog_breaking": "Changements incompatibles :",
    "update.changelog_features": "Nouvelles fonctionnalités :",
    "update.changelog_fixes": "Corrections de bugs :",
    "update.changelog_other": "Autres modifications :",
    "update.current_commit": "   Actuel : {commit}...",
    "update.target_commit": "   Cible :  {commit}...",
    "update.unknown_version": "Attention : impossible de déterminer la version actuelle du modèle",
    "update.untagged_commit": (
        "Le projet a peut-être été généré depuis un commit non tagué"
    ),
    "update.custom_template": "Utilisation d'un modèle personnalisé ({source}) : {path}",
    "update.version_info": "Informations de version :",
    "update.current_cli": "   CLI actuel :      {version}",
    "update.current_template": "   Modèle actuel :   {version}",
    "update.current_template_commit": "   Modèle actuel :   {commit}... (commit)",
    "update.current_template_unknown": "   Modèle actuel :   inconnu",
    "update.target_template": "   Modèle cible :    {version}",
    "update.already_at_version": "Le projet est déjà à la version demandée",
    "update.already_at_commit": "Le projet est déjà au commit cible",
    "update.ahead_of_target": (
        "Le projet est plus récent que la version de modèle cible"
    ),
    "update.ahead_of_target_hint": (
        "Rien à mettre à jour. Utilisez --to-version pour cibler une version précise."
    ),
    "update.downgrade_blocked": "Rétrogradation non supportée",
    "update.downgrade_reason": (
        "Copier ne supporte pas la rétrogradation vers des versions antérieures du modèle."
    ),
    "update.changelog": "Journal des modifications :",
    "update.dry_run": "MODE SIMULATION - Aucune modification ne sera appliquée",
    "update.dry_run_hint": "Pour appliquer cette mise à jour, exécutez :",
    "update.confirm": "Appliquer cette mise à jour ?",
    "update.cancelled": "Mise à jour annulée",
    "update.creating_backup": "Création d'un point de sauvegarde...",
    "update.backup_created": "   Sauvegarde créée : {tag}",
    "update.backup_failed": "Impossible de créer le point de sauvegarde",
    "update.updating": "Mise à jour du projet...",
    "update.updating_to": "Mise à jour vers la version {version} du modèle",
    "update.moved_files": "   {count} nouveaux fichiers déplacés depuis le répertoire imbriqué",
    "update.synced_files": "   {count} modifications de modèle synchronisées",
    "update.merge_conflicts": (
        "   {count} fichier(s) avec des conflits de fusion (cherchez <<<<<<< pour résoudre) :"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "Exécution des tâches post-génération...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": "   __aegis_version__ mis à jour vers {version}",
    "update.success": "Mise à jour terminée !",
    "update.partial_success": (
        "Mise à jour terminée avec des échecs de tâches post-génération"
    ),
    "update.partial_detail": "   Certaines tâches de configuration ont échoué. Voir les détails ci-dessus.",
    "update.next_steps": "Prochaines étapes :",
    "update.next_review": "   1. Examiner les modifications : git diff",
    "update.next_conflicts": "   2. Vérifier les conflits (fichiers *.rej)",
    "update.next_test": "   3. Exécuter les tests : make check",
    "update.next_commit": "   4. Valider les modifications : git add . && git commit",
    "update.failed": "Mise à jour échouée : {error}",
    "update.rollback_prompt": "Revenir à l'état précédent ?",
    "update.manual_rollback": "Rollback manuel : git reset --hard {tag}",
    "update.troubleshooting": "Dépannage :",
    "update.troubleshoot_clean": "   - Assurez-vous d'avoir un arbre git propre",
    "update.troubleshoot_version": "   - Vérifiez que la version/le commit existe",
    "update.troubleshoot_docs": "   - Consultez la documentation Copier pour les problèmes de mise à jour",
    # ── Ingress command ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack - Activation du TLS Ingress",
    "ingress.project": "Projet : {path}",
    "ingress.not_found": "Composant ingress introuvable. Ajout en cours...",
    "ingress.add_confirm": "Ajouter le composant ingress ?",
    "ingress.add_failed": "Échec de l'ajout du composant ingress : {error}",
    "ingress.added": "Composant ingress ajouté.",
    "ingress.tls_already": "TLS est déjà activé sur ce projet.",
    "ingress.domain_label": "   Domaine : {domain}",
    "ingress.acme_email": "   E-mail ACME : {email}",
    "ingress.domain_prompt": (
        "Nom de domaine (ex. : example.com, ou vide pour le routage par IP)"
    ),
    "ingress.email_reuse": "Utilisation de l'e-mail existant pour ACME : {email}",
    "ingress.email_prompt": "E-mail pour les notifications Let's Encrypt",
    "ingress.email_required": (
        "Erreur : --email est requis pour TLS (nécessaire pour Let's Encrypt)"
    ),
    "ingress.tls_config": "Configuration TLS :",
    "ingress.domain_none": "   Domaine : (aucun - routage par IP/PathPrefix)",
    "ingress.tls_confirm": "Activer TLS avec cette configuration ?",
    "ingress.enabling": "Activation du TLS...",
    "ingress.updated_file": "   Mis à jour : {file}",
    "ingress.created_file": "   Créé : {file}",
    "ingress.success": "TLS activé !",
    "ingress.available_at": "   Votre application sera disponible à : https://{domain}",
    "ingress.https_configured": "   HTTPS est maintenant configuré avec Let's Encrypt",
    "ingress.next_steps": "Prochaines étapes :",
    "ingress.next_deploy": "   1. Déployer avec : aegis deploy",
    "ingress.next_ports": "   2. Assurez-vous que les ports 80 et 443 sont ouverts sur votre serveur",
    "ingress.next_dns": (
        "   3. Pointez votre enregistrement DNS A pour {domain} vers l'IP de votre serveur"
    ),
    "ingress.next_certs": "   Les certificats seront provisionnés automatiquement à la première requête",
    # ── Deploy commands ────────────────────────────────────────────────
    "deploy.no_config": (
        "Aucune configuration de déploiement trouvée. Exécutez « aegis deploy-init » d'abord."
    ),
    "deploy.init_saved": "Configuration de déploiement enregistrée dans {file}",
    "deploy.init_host": "   Hôte : {host}",
    "deploy.init_user": "   Utilisateur : {user}",
    "deploy.init_path": "   Chemin : {path}",
    "deploy.init_docker_context": "   Contexte Docker : {context}",
    "deploy.prompt_host": "IP ou nom d'hôte du serveur",
    "deploy.init_gitignore": (
        "Note : pensez à ajouter .aegis/ dans .gitignore pour ne pas versionner la configuration de déploiement"
    ),
    "deploy.setup_title": "Configuration du serveur {target}...",
    "deploy.checking_ssh": "Vérification de la connectivité SSH...",
    "deploy.adding_host_key": "Ajout du serveur aux known_hosts...",
    "deploy.ssh_keyscan_failed": "Échec du scan de la clé SSH de l'hôte : {error}",
    "deploy.ssh_failed": "Connexion SSH échouée : {error}",
    "deploy.copying_script": "Copie du script de configuration vers le serveur...",
    "deploy.copy_failed": "Échec de la copie du script de configuration",
    "deploy.running_setup": "Exécution de la configuration du serveur (peut prendre quelques minutes)...",
    "deploy.setup_failed": "Configuration du serveur échouée",
    "deploy.setup_script_missing": "Script de configuration du serveur introuvable : {path}",
    "deploy.setup_script_hint": (
        "Assurez-vous que votre projet créé avec le composant ingress."
    ),
    "deploy.setup_complete": "Configuration du serveur terminée !",
    "deploy.setup_verify": "Vérification de l'installation :",
    "deploy.setup_verify_docker": "  Docker : {version}",
    "deploy.setup_verify_compose": "  Docker Compose : {version}",
    "deploy.setup_verify_uv": "  uv : {version}",
    "deploy.setup_verify_app_dir": "  Répertoire de l'application : {path}",
    "deploy.setup_next": "Ensuite : exécutez « aegis deploy » pour déployer votre application",
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
    "deploy.deploying": "Déploiement vers {host}...",
    "deploy.creating_backup": "Création de la sauvegarde {timestamp}...",
    "deploy.backup_failed": "Échec de la création de la sauvegarde : {error}",
    "deploy.backup_db": "Sauvegarde de la base de données PostgreSQL...",
    "deploy.backup_db_neon": "La base de données est gérée par Neon (branches / restauration à un instant donné) ; sauvegarde locale ignorée",
    "deploy.backup_db_failed": (
        "Attention : la sauvegarde de la base de données a échoué, poursuite sans sauvegarde"
    ),
    "deploy.backup_created": "Sauvegarde créée : {timestamp}",
    "deploy.backup_pruned": "Ancienne sauvegarde supprimée : {name}",
    "deploy.no_existing": "Aucun déploiement existant trouvé, sauvegarde ignorée",
    "deploy.syncing": "Synchronisation des fichiers vers le serveur...",
    "deploy.mkdir_failed": "Impossible de créer le répertoire distant « {path} »",
    "deploy.sync_failed": "Échec de la synchronisation des fichiers",
    "deploy.copying_env": "Copie de {file} vers le serveur en tant que .env...",
    "deploy.env_copy_failed": "Échec de la copie du fichier .env",
    "deploy.stopping": "Arrêt des services existants...",
    "deploy.building": "Construction et démarrage des services sur le serveur...",
    "deploy.start_failed": "Échec du démarrage des services",
    "deploy.auto_rollback": "Rollback automatique vers la version précédente...",
    "deploy.health_waiting": "Attente de la stabilisation des conteneurs...",
    "deploy.health_attempt": "Vérification de santé {n}/{total}...",
    "deploy.health_passed": "Vérification de santé réussie",
    "deploy.health_retry": "Vérification de santé échouée, nouvelle tentative dans {interval}s...",
    "deploy.health_all_failed": "Toutes les vérifications de santé ont échoué",
    "deploy.rolled_back": "Rollback vers la sauvegarde {timestamp} effectué",
    "deploy.rollback_failed": "Rollback échoué ! Intervention manuelle requise.",
    "deploy.health_failed_hint": (
        "Déploiement terminé mais la vérification de santé a échoué. Consultez les logs avec : aegis deploy-logs"
    ),
    "deploy.complete": "Déploiement terminé !",
    "deploy.rolling_starting": "Déploiement continu vers {host}...",
    "deploy.rolling_building": "Construction de l'image du serveur web...",
    "deploy.rolling_pausing": "Mise en pause de la file des workers...",
    "deploy.rolling_pause_failed": (
        "Impossible d'activer le drapeau de pause ; les workers risquent "
        "de recevoir SIGTERM en plein traitement."
    ),
    "deploy.rolling_draining": (
        "Attente jusqu'à {seconds}s pour le drainage des workers..."
    ),
    "deploy.rolling_drain_timeout": (
        "Les workers n'ont pas été drainés à temps. Drapeau de pause effacé ; abandon."
    ),
    "deploy.rolling_recreating": "Recréation : {services}",
    "deploy.rolling_webserver": (
        "Redémarrage continu du serveur web "
        "(attente jusqu'à {seconds}s que le conteneur soit sain)..."
    ),
    "deploy.rolling_rollout_failed": (
        "docker rollout a échoué. Le plugin est-il installé sous "
        "~/.docker/cli-plugins/ sur l'hôte de déploiement ?"
    ),
    "deploy.rolling_complete": "Déploiement continu terminé !",
    "deploy.app_running": "   Application accessible à : http://{host}",
    "deploy.overseer": "   Tableau de bord Overseer : http://{host}/dashboard/",
    "deploy.view_logs": "   Voir les logs : aegis deploy-logs",
    "deploy.check_status": "   Vérifier le statut : aegis deploy-status",
    "deploy.backup_complete": "Sauvegarde terminée !",
    "deploy.creating_backup_on": "Création de la sauvegarde sur {host}...",
    "deploy.no_backups": "Aucune sauvegarde trouvée.",
    "deploy.backups_header": "Sauvegardes sur {host} ({count} au total) :",
    "deploy.col_timestamp": "Horodatage",
    "deploy.col_size": "Taille",
    "deploy.col_database": "Base de données",
    "deploy.rollback_hint": (
        "Rollback avec : aegis deploy-rollback --backup <horodatage>"
    ),
    "deploy.no_backups_available": "Aucune sauvegarde disponible.",
    "deploy.rolling_back": "Rollback vers la sauvegarde {backup} sur {host}...",
    "deploy.rollback_not_found": "Sauvegarde introuvable : {timestamp}",
    "deploy.rollback_stopping": "Arrêt des services...",
    "deploy.rollback_restoring": "Restauration des fichiers depuis la sauvegarde {timestamp}...",
    "deploy.rollback_restore_failed": "Échec de la restauration des fichiers : {error}",
    "deploy.rollback_db": "Restauration de la base de données...",
    "deploy.rollback_db_neon": "La récupération de la base de données est gérée par Neon (branches / restauration à un instant donné) ; restauration locale ignorée",
    "deploy.rollback_pg_wait": "Attente de la disponibilité de PostgreSQL...",
    "deploy.rollback_pg_timeout": (
        "PostgreSQL n'est pas devenu disponible, tentative de restauration malgré tout"
    ),
    "deploy.rollback_db_failed": "Attention : la restauration de la base de données a échoué",
    "deploy.rollback_starting": "Démarrage des services...",
    "deploy.rollback_start_failed": "Échec du démarrage des services après le rollback",
    "deploy.rollback_complete": "Rollback terminé !",
    "deploy.rollback_failed_final": "Rollback échoué !",
    "deploy.status_header": "Statut des services sur {host} :",
    "deploy.stop_stopping": "Arrêt des services...",
    "deploy.stop_success": "Services arrêtés",
    "deploy.stop_failed": "Échec de l'arrêt des services",
    "deploy.restart_restarting": "Redémarrage des services...",
    "deploy.restart_success": "Services redémarrés",
    "deploy.restart_failed": "Échec du redémarrage des services",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": "Chemin vers le projet Aegis Stack (par défaut : répertoire courant)",
    "common.help_project_path": "Chemin vers le projet (par défaut : répertoire courant)",
    "common.help_yes": "Ignorer confirmation",
    "common.help_yes_plural": "Ignorer toutes les confirmations",
    "common.help_interactive_components": "Sélectionner les composants interactivement",
    "common.help_interactive_services": "Sélectionner les services interactivement",
    "common.help_force": "Forcer malgré les avertissements d'incompatibilité de version",
    # ── init CLI help ──────────────────────────────────────────────────
    "blueprints.title": "AVAILABLE BLUEPRINTS",
    "blueprints.none_available": "No blueprints available.",
    "blueprints.includes": "Includes: {names}",
    "blueprints.usage_hint": "Start a project from one:",
    "init.help_opt_blueprint": (
        "Start from a named blueprint (a preset component/service selection)"
    ),
    "init.unknown_blueprint": "Unknown blueprint: {name}. Available: {available}",
    "init.help_arg_name": "Nom du nouveau projet Aegis Stack à créer",
    "init.help_opt_components": "Liste de composants séparés par des virgules (redis,worker,scheduler,database)",
    "init.help_opt_python": "Version de Python pour le projet généré (3.11, 3.12, 3.13 ou 3.14)",
    "init.help_opt_force": "Écraser le répertoire existant s'il existe déjà",
    "init.help_opt_directory": "Répertoire dans lequel créer le projet (par défaut : répertoire courant)",
    "init.help_opt_template_version": "Générer depuis une version spécifique du modèle (tag, commit ou branche)",
    "init.help_opt_no_llm_sync": "Ignorer la synchronisation du catalogue LLM après la génération (service AI uniquement)",
    "init.help_opt_dev": "Mode dev : lire les modèles depuis l'arbre de travail (modifications non committées incluses)",
    "init.help_opt_services": "Services : {services}. Options AI : ai[framework,backend,providers] avec framework={frameworks}, backend={backends}, providers={providers}",
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": "Liste de composants à ajouter, séparés par des virgules (scheduler,worker,database)",
    "add.help_opt_scheduler_backend": "Backend du scheduler : « memory » (par défaut) ou « sqlite » (active la persistance)",
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "Mettre à jour vers une version spécifique (par défaut : la plus récente)",
    "update.help_opt_dry_run": "Prévisualiser les changements sans les appliquer",
    "update.help_opt_template_path": "Utiliser un chemin de modèle personnalisé plutôt que la version installée",
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": "Liste de composants à supprimer, séparés par des virgules (scheduler,worker,database)",
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": "Liste de services à ajouter, séparés par des virgules (auth,ai)",
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": "Liste de services à supprimer, séparés par des virgules (auth,ai,comms)",
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": "Nom de domaine pour le certificat TLS (p. ex. example.com)",
    "ingress.help_opt_email": "Adresse e-mail pour les notifications de certificat Let's Encrypt",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "Adresse IP ou nom d'hôte du serveur",
    "deploy.help_opt_user": "Utilisateur SSH pour le déploiement",
    "deploy.help_opt_path": "Chemin de déploiement sur le serveur",
    "deploy.help_opt_public_key": "Chemin vers une clé publique à installer dans authorized_keys de l'utilisateur de déploiement (idempotent). Utilisez-le pour éviter de lancer ssh-copy-id à la main avant le déploiement.",
    "deploy.help_opt_build": "Construire les images avant le déploiement",
    "deploy.help_opt_backup": "Créer une sauvegarde avant le déploiement",
    "deploy.help_opt_health": "Exécuter un contrôle de santé après le déploiement",
    "deploy.help_opt_rolling": (
        "Déploiement code-only sans interruption HTTP. Roule le serveur "
        "web via docker-rollout et met en pause la file des workers pour "
        "que les jobs en cours se terminent proprement. Ignore les "
        "migrations de base de données."
    ),
    "deploy.help_opt_drain_timeout": (
        "Secondes d'attente pour le drainage des workers après la mise "
        "en pause de la file lors d'un déploiement continu (défaut : 90)."
    ),
    "deploy.help_opt_rollout_timeout": (
        "Secondes pendant lesquelles docker-rollout attend que le nouveau "
        "serveur web soit sain lors d'un déploiement continu. À "
        "dimensionner selon le budget HEALTHCHECK du conteneur "
        "(start_period + retries × interval), et non un délai fixe de 60s "
        "(défaut : 900)."
    ),
    "deploy.help_opt_rollback_backup": "Horodatage de la sauvegarde vers laquelle revenir (par défaut : la plus récente)",
    "deploy.help_opt_logs_follow": "Suivre la sortie des logs en continu",
    "deploy.help_opt_logs_service": "Afficher uniquement les logs d'un service donné",
    "deploy.help_opt_shell_service": "Service auquel se connecter",
    "deploy.help_opt_gh_repo": "Dépôt GitHub au format owner/name (par défaut : détection auto depuis git remote origin)",
    "deploy.help_opt_gh_tags": "Déclencher aussi le workflow de déploiement lors des push sur les tags v*",
    "deploy.help_opt_gh_overwrite": "Écraser les secrets GitHub et le workflow deploy.yml existants",
    "deploy.help_opt_dry_run": "Afficher les actions prévues sans rien modifier",
    "deploy.help_opt_local_key_path": "Chemin où copier la clé privée générée avant le nettoyage. Par défaut : pas de copie locale (la clé n'existe que dans les secrets GitHub).",
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "Inspecter les plugins Aegis installés et rechercher dans le registre",
    "plugins.cannot_read_answers": "Impossible de lire {path} : {error}. Les vérifications de compatibilité seront ignorées.",
    "plugins.help_list": "Lister les plugins installés et leur compatibilité avec ce projet.",
    "plugins.help_opt_list_project_path": "Projet sur lequel évaluer la compatibilité (par défaut : le répertoire courant s'il s'agit d'un projet Aegis).",
    "plugins.help_opt_list_verbose": "Afficher la colonne description.",
    "plugins.section_in_tree": "Intégrés (officiels)",
    "plugins.section_external": "Plugins externes",
    "plugins.col_name": "Nom",
    "plugins.col_version": "Version",
    "plugins.col_kind": "Type",
    "plugins.col_description": "Description",
    "plugins.col_status": "Statut",
    "plugins.no_external_installed": "Aucun plugin externe installé. Installez-en un avec : pip install aegis-plugin-<name>",
    "plugins.help_info": "Afficher les informations détaillées d'un plugin.",
    "plugins.help_arg_info_name": "Nom du plugin (p. ex. « auth », « scraper »)",
    "plugins.help_opt_info_project_path": "Projet sur lequel évaluer la compatibilité.",
    "plugins.not_installed_named": "Aucun plugin nommé « {name} » n'est installé.",
    "plugins.available_list": "Disponibles : {names}",
    "plugins.label_first_party": "(officiel)",
    "plugins.label_verified": "(vérifié)",
    "plugins.label_unverified": "(communauté, non vérifié)",
    "plugins.label_kind": "Type :",
    "plugins.label_type": "Sous-type :",
    "plugins.label_requires_components": "Composants requis :",
    "plugins.label_recommends_components": "Recommandés :",
    "plugins.label_requires_services": "Services requis :",
    "plugins.label_requires_plugins": "Plugins requis :",
    "plugins.label_conflicts": "Conflits :",
    "plugins.label_python_deps": "Dépendances Python :",
    "plugins.deps_more": "(+{count} autres)",
    "plugins.section_options": "Options",
    "plugins.option_choices": "valeurs :",
    "plugins.option_default": "par défaut :",
    "plugins.option_auto_requires": "(avec auto_requires)",
    "plugins.info_files": "Fichiers : {files}   Migrations : {migrations} ({tables} tables)   CLI : {cli}",
    "plugins.cli_yes": "oui",
    "plugins.cli_no": "non",
    "plugins.section_compat": "Compatibilité",
    "plugins.help_update": "Régénérer les modèles d'un plugin installé à sa version pip courante.",
    "plugins.help_arg_update_name": "Plugin à mettre à jour. Obligatoire sauf si --all est utilisé.",
    "plugins.help_opt_update_all": "Mettre à jour tous les plugins listés dans _plugins du projet.",
    "plugins.help_opt_update_force": "Appliquer la mise à jour même si la contrainte aegis_version du nouveau plugin exclut la CLI en cours.",
    "plugins.update_need_target": "Indiquez un nom de plugin ou utilisez --all.",
    "plugins.update_either_not_both": "Passez un nom de plugin OU --all, pas les deux.",
    "plugins.update_no_plugins_installed": "Aucun plugin n'est installé dans ce projet.",
    "plugins.update_not_in_project": "Le plugin « {name} » n'est pas installé dans ce projet.",
    "plugins.update_use_list_hint": "Utilisez `aegis plugins list` pour voir les plugins disponibles, et `aegis add <name>` pour les installer.",
    "plugins.update_not_pip_installed": "Le plugin « {name} » figure dans _plugins du projet mais n'est pas installé via pip ; lancez d'abord `pip install aegis-plugin-{name}`.",
    "plugins.update_already_at": "{name} (déjà en {version})",
    "plugins.local_changes_replaced": (
        "Replaced {count} locally-modified file(s) owned by '{name}'. "
        "Plugin files are re-rendered on install; your previous versions "
        "were saved to {path}"
    ),
    "plugins.update_forcing": "Mise à jour forcée malgré l'incompatibilité de version : {error}",
    "plugins.update_progress": "Mise à jour du plugin : {name} ({old} → {new})",
    "plugins.update_confirm_apply": "Appliquer la mise à jour à « {name} » ?",
    "plugins.update_skipped_by_user": "{name} (ignoré par l'utilisateur)",
    "plugins.update_legacy_strings": "Entrées _plugins au format chaîne ignorées : {entries}. Réajoutez-les avec `aegis add <name>` pour migrer vers le format dict actuel.",
    "plugins.update_summary_updated": "Mis à jour : {count}",
    "plugins.update_summary_skipped": "Ignorés : {count}",
    "plugins.update_summary_failed": "Échoués : {count}",
    "plugins.help_create": "Générer le squelette d'un nouveau paquet Python aegis-plugin-<name>.",
    "plugins.help_arg_create_name": "Nom du plugin (minuscules, sans tirets). Devient le paquet Python aegis_plugin_<name> et le nom d'installation aegis-plugin-<name>.",
    "plugins.help_opt_create_target": "Répertoire parent dans lequel générer le squelette.",
    "plugins.help_opt_create_author": "Chaîne auteur pour pyproject.toml et le README.",
    "plugins.help_opt_create_description": "Description du plugin en une ligne.",
    "plugins.create_target_missing": "Le répertoire cible n'existe pas : {target}",
    "plugins.create_already_exists": "Le répertoire existe déjà : {output}",
    "plugins.create_pick_different": "Choisissez un autre nom ou supprimez le répertoire existant.",
    "plugins.create_starting": "Création du plugin : {name}",
    "plugins.create_label_target": "Cible :",
    "plugins.create_label_author": "Auteur :",
    "plugins.create_label_description": "Description :",
    "plugins.create_default_marker": "(par défaut)",
    "plugins.create_confirm": "Générer le squelette ?",
    "plugins.create_cancelled": "Annulé.",
    "plugins.create_success": "{count} fichiers créés dans {output}",
    "plugins.create_next_steps_header": "Étapes suivantes :",
    "plugins.create_next_steps_confirm_comment": "vérifier que le plugin est bien détecté",
    "plugins.create_next_steps_edit_comment": "modifiez src/aegis_plugin_<name>/plugin.py pour ajouter le câblage",
    "plugins.help_search": "Rechercher dans le registre officiel des plugins.",
    "plugins.help_arg_search_keyword": "Mot-clé de recherche optionnel",
    "plugins.search_not_available": "Le registre des plugins n'est pas encore disponible.",
    "plugins.search_install_hint": "Pour l'instant : pip install aegis-plugin-<name>, puis aegis plugins list.",
    "plugins.search_future_keyword": "Une fois le registre en ligne, cette commande recherchera « {keyword} ».",
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "Des applications Python prêtes pour la production dès le premier jour.",
    "guided.welcome.body": "Cette configuration guidée parcourt chaque brique avec une brève explication afin que vous décidiez ce dont votre projet a besoin. Ne choisissez que ce que vous voulez maintenant ; tout le reste pourra être ajouté plus tard avec 'aegis add'.",
    "guided.corestack.title": "INCLUS DANS CHAQUE PROJET",
    "guided.corestack.body": "Chaque projet Aegis commence par ces deux éléments, reliés entre eux et prêts à l'emploi.",
    "guided.sidebar.components": "COMPOSANTS",
    "guided.sidebar.services": "SERVICES",
    "guided.prompt.worker_backend": "Choisissez un backend de worker",
    "guided.prompt.scheduler_backend": "Persistance du planificateur : conserver l'historique des tâches après redémarrage ?",
    "guided.prompt.database_engine": "Moteur de base de données pour {context}",
    "guided.prompt.postgres_provider": "Hôte PostgreSQL pour {context}",
    "guided.prompt.auth_level": "Niveau d'authentification",
    "guided.prompt.ai_framework": "Framework IA",
    "guided.prompt.ai_providers": "Fournisseurs IA : choisissez ceux à intégrer",
    "guided.prompt.ai_storage": "Stockage des conversations IA",
    "guided.prompt.ai_rag": "Ajouter le RAG : un chat basé sur vos propres documents et votre code ?",
    "guided.prompt.ai_voice": "Ajouter la voix : synthèse et reconnaissance vocale ?",
    "guided.note.one_datastore": "Un seul datastore par projet : le moteur choisi ici définit la base de données du projet, partagée par tout ce qui stocke des données.",
    "guided.note.one_database_host": "Une seule base de données par projet : cet hôte sert tout ce qui stocke des données.",
    "guided.multi.hint": "Cochez autant que vous le souhaitez, puis choisissez Continuer.",
    "guided.choice.add": "Ajouter",
    "guided.choice.skip": "Ignorer",
    "guided.screen.add_question": "Ajouter {name} ?",
    "guided.screen.too_small": "Terminal trop petit. Agrandissez-le à au moins {w}x{h}.",
    "guided.review.title": "VOTRE CONFIGURATION",
    "guided.review.files_pane": "FICHIERS DE COMPOSANTS",
    "guided.review.deps_pane": "DÉPENDANCES",
    "guided.review.counts": "{files} fichiers de composants · {deps} dépendances",
    "guided.building.title": "Génération de {name} …",
    "guided.building.preparing": "Préparation …",
    "guided.building.note": "Cela peut prendre une minute ou deux ; uv fait le gros du travail.",
    "guided.hint.building": "génération …",
    "guided.done.ready": "{name} est prêt",
    "guided.done.body": "Projet généré et dépendances installées.",
    "guided.done.next_steps": "PROCHAINES ÉTAPES",
    "guided.done.project_structure": "STRUCTURE DU PROJET",
    "guided.done.recreate": "RECRÉEZ CETTE CONFIGURATION À TOUT MOMENT",
    "guided.done.copy_note": "Appuyez sur c pour copier ; la commande complète s'affiche aussi ci-dessous une fois terminé.",
    "guided.done.copied": "Copié dans le presse-papiers ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "Continuer",
    "guided.header.label": "configuration guidée",
    "guided.hint.move": "déplacer",
    "guided.hint.select": "sélectionner",
    "guided.hint.toggle": "basculer",
    "guided.hint.back": "retour",
    "guided.hint.begin": "commencer",
    "guided.hint.build": "générer",
    "guided.hint.next": "suivant",
    "guided.hint.finish": "terminer",
    "guided.hint.quit": "quitter",
    "guided.hint.services": "passer aux services",
    "guided.hint.copy": "copier la commande",
    "guided.hint.deps": "dépendances",
    "guided.hint.files": "fichiers",
    "guided.review.core": "Cœur :",
    "guided.review.infrastructure": "Infrastructure :",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "Services :",
    "guided.review.auto": "auto",
    "guided.review.build": "Générer {name}",
    "guided.review.more": "… +{n} de plus",
    "guided.screen.requires": "Nécessite :",
    "guided.screen.added_automatically": "(ajouté automatiquement)",
    "guided.screen.pairs": "Se combine bien avec :",
    "guided.screen.docs": "Docs :",
    "component.backend.long": "Une application FastAPI qui sert votre API, asynchrone de bout en bout : routes typées, documentation OpenAPI automatique, contrôles de santé et une suite de tests qui couvre déjà l'ensemble.",
    "component.frontend.long": "Un tableau de bord Flet qui affiche en temps réel l'état du système et de chaque composant choisi ici, prêt à être étendu avec vos propres vues. Du Python de bout en bout, sans chaîne de build JavaScript.",
    "component.worker.long": "Traitement des tâches en arrière-plan avec le backend de votre choix : arq (par défaut), Dramatiq ou TaskIQ. Déchargez le travail lent comme les e-mails, les exports et les appels d'API tierces pour que les requêtes restent rapides. Fonctionne sur Redis, ajouté automatiquement.",
    "component.scheduler.long": "Planification de tâches en arrière-plan et tâches cron avec APScheduler. Exécutez des tâches périodiques comme les nettoyages, les rapports et les contrôles de santé selon un calendrier. La persistance optionnelle en base de données conserve l'historique des tâches et survit aux redémarrages.",
    "component.database.long": "Stockage persistant avec l'ORM SQLModel, les migrations Alembic et le pooling de connexions. SQLite vous offre une base de données fichier sans configuration pour le développement ; PostgreSQL est le choix pour la production. La plupart des services s'appuient dessus.",
    "component.redis.long": "Magasin de données en mémoire utilisé comme cache et courtier de messages. Alimente les files de tâches en arrière-plan et la messagerie pub/sub entre vos services, et offre aux gestionnaires de requêtes un cache partagé rapide.",
    "component.ingress.long": "Proxy inverse et routage du trafic avec Traefik : découverte automatique des services, protection des points d'accès d'administration et TLS optionnel via Let's Encrypt. La porte d'entrée des déploiements.",
    "component.observability.long": "Traçage distribué, métriques et corrélation des journaux avec Pydantic Logfire. Instrumente automatiquement votre application et s'adapte aux composants activés, pour que vous voyiez ce que fait réellement la production.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "Gestion complète des utilisateurs avec authentification JWT, cookies de session et rotation des jetons de rafraîchissement. Trois niveaux : e-mail/mot de passe basique, rôles et permissions RBAC, ou organisations multi-locataires. Inclut l'inscription, la connexion et un onglet de tableau de bord d'administration.",
    "service.ai.long": "Une plateforme IA complète : chat multi-fournisseurs, un catalogue de LLM d'environ 2000 modèles, suivi des coûts avec analyses d'utilisation, RAG optionnel pour des conversations qui connaissent votre code, et voix optionnelle (TTS/STT). Choisissez Pydantic AI ou LangChain comme framework.",
    "service.comms.long": "E-mail, SMS et appels vocaux via des fournisseurs reconnus : Resend pour l'e-mail, Twilio pour le SMS et la voix. Les deux proposent des offres gratuites, vous pouvez donc démarrer sans carte bancaire.",
    "service.insights.long": "Suivi automatique de l'adoption de votre projet sur GitHub, PyPI, Plausible Analytics et Reddit. Collecte selon un calendrier, conserve l'historique et visualise la croissance dans le tableau de bord.",
    "service.payment.long": "Traitement des paiements avec Stripe : sessions de paiement, abonnements, webhooks et remboursements. Le mode test de Stripe ne nécessite pas de carte bancaire, vous pouvez donc construire tout le parcours avant la mise en production.",
    "service.blog.long": "Publication Markdown native avec des billets stockés en base de données, des tags, des brouillons et une interface d'édition dans le tableau de bord. Importez et exportez les billets en Markdown brut avec frontmatter.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "En mémoire",
    "guided.choice.scheduler.memory": "Pas de persistance. Les tâches sont réinitialisées au redémarrage — ignorez en cas de doute.",
    "guided.choice.scheduler.sqlite": "Conserve l'historique des tâches dans une base de données fichier.",
    "guided.choice.scheduler.postgres": "Conserve l'historique des tâches, niveau production.",
    "guided.choice.worker.arq": "Worker asynchrone simple et bien testé, avec une configuration minimale. Idéal pour les tâches liées aux E/S. Le choix par défaut.",
    "guided.choice.worker.dramatiq": "Modèle d'acteurs multi-processus. Idéal pour les tâches gourmandes en CPU qui profitent de plusieurs processus système.",
    "guided.choice.worker.taskiq": "Asynchrone par nature, avec des brokers par file et un transport Redis Streams avec accusés de réception.",
    "guided.choice.db.sqlite": "Base de données fichier sans configuration. Parfaite pour le développement.",
    "guided.choice.db.postgres": "Niveau production, connexions mutualisées.",
    "guided.choice.db_provider.container": "Conteneur local postgres:16, dev et prod.",
    "guided.choice.db_provider.neon": (
        "Postgres serverless : cloud en prod, conteneur local en dev."
    ),
    "guided.choice.auth.basic": "E-mail et mot de passe avec sessions JWT.",
    "guided.choice.auth.rbac": "Ajoute des rôles et des permissions.",
    "guided.choice.auth.org": "Organisations multi-locataires.",
    "guided.choice.framework.pydantic_ai": "Typé et léger. Le choix par défaut.",
    "guided.choice.framework.langchain": "Vaste écosystème, nombreuses intégrations.",
    "guided.choice.storage.memory": "Aucun historique, rien à configurer.",
    "guided.choice.storage.sqlite": "Historique de conversation persistant dans une base de données fichier.",
    "guided.choice.storage.postgres": "Persistant et de niveau production.",
    "guided.choice.provider.public.desc": "Point d'accès public gratuit",
    "guided.choice.provider.public.pricing": "Gratuit, sans clé d'API",
    "guided.choice.provider.openai.desc": "Modèles GPT",
    "guided.choice.provider.openai.pricing": "Payant",
    "guided.choice.provider.anthropic.desc": "Modèles Claude",
    "guided.choice.provider.anthropic.pricing": "Payant",
    "guided.choice.provider.google.desc": "Modèles Gemini",
    "guided.choice.provider.google.pricing": "Offre gratuite (Flash uniquement)",
    "guided.choice.provider.groq.desc": "Inférence rapide",
    "guided.choice.provider.groq.pricing": "Offre gratuite",
    "guided.choice.provider.mistral.desc": "Modèles ouverts",
    "guided.choice.provider.mistral.pricing": "Surtout payant",
    "guided.choice.provider.cohere.desc": "Orientation entreprise",
    "guided.choice.provider.cohere.pricing": "Gratuit limité",
    "guided.choice.provider.ollama.desc": "Inférence locale",
    "guided.choice.provider.ollama.pricing": "Gratuit (local)",
    "build.step.render": "Génération des fichiers du projet",
    "build.step.deps": "Installation des dépendances",
    "build.step.env": "Configuration de l'environnement",
    "build.step.migrate": "Application des migrations",
    "build.step.llm": "Synchronisation du catalogue LLM",
    "build.step.format": "Formatage du code",
}
