"""Korean locale — 한국어 메시지 정의."""

MESSAGES: dict[str, str] = {
    # ── Validation ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "프로젝트 이름이 유효하지 않습니다. 영문자, 숫자, 하이픈, "
        "밑줄만 사용할 수 있습니다."
    ),
    "validation.reserved_name": "'{name}'은(는) 예약된 이름입니다.",
    "validation.name_too_long": (
        "프로젝트 이름이 너무 깁니다. 최대 50자까지 허용됩니다."
    ),
    "validation.invalid_python": (
        "Python 버전 '{version}'이(가) 유효하지 않습니다. 다음 중 하나여야 합니다: {supported}"
    ),
    "validation.unknown_service": "알 수 없는 서비스: {name}",
    "validation.unknown_services": "알 수 없는 서비스: {names}",
    "validation.unknown_component": "알 수 없는 컴포넌트: {name}",
    # ── Init command ───────────────────────────────────────────────────
    "init.title": "Aegis Stack 프로젝트 초기화",
    "init.location": "위치:",
    "init.template_version": "템플릿 버전:",
    "init.dir_exists": "디렉토리 '{path}'이(가) 이미 존재합니다",
    "init.dir_exists_hint": "--force로 덮어쓰거나 다른 이름을 선택하세요",
    "init.overwriting": "기존 디렉토리 덮어쓰는 중: {path}",
    "init.services_require": "서비스에 필요한 컴포넌트: {components}",
    "init.compat_errors": "서비스-컴포넌트 호환성 오류:",
    "init.suggestion_add": ("제안: 누락된 컴포넌트 추가 --components {components}"),
    "init.suggestion_remove": (
        "또는 --components를 제거하여 서비스가 자동으로 의존성을 추가하도록 하세요."
    ),
    "init.suggestion_interactive": (
        "또는 대화형 모드를 사용하여 서비스 의존성을 자동 추가하세요."
    ),
    "init.auto_detected_scheduler": ("자동 감지: {backend} 영속성 포함 스케줄러"),
    "init.auto_added_deps": "자동 추가된 의존성: {deps}",
    "init.auto_added_by_services": "서비스에 의해 자동 추가됨:",
    "init.required_by": "{services}에 필요",
    "init.config_title": "프로젝트 구성",
    "init.config_name": "이름:",
    "init.config_core": "코어:",
    "init.config_infra": "인프라:",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "서비스:",
    "init.component_files": "컴포넌트 파일:",
    "init.entrypoints": "진입점:",
    "init.worker_queues": "Worker 큐:",
    "init.dependencies": "설치될 의존성:",
    "init.confirm_create": "이 프로젝트를 생성하시겠습니까?",
    "init.cancelled": "프로젝트 생성 취소됨",
    "init.removing_dir": "기존 디렉토리 삭제 중: {path}",
    "init.creating": "프로젝트 생성 중: {name}",
    "init.error": "프로젝트 생성 오류: {error}",
    "init.replay_hint": "이 스택은 언제든 다시 생성할 수 있습니다:",
    # ── Interactive: section headers ───────────────────────────────────
    "interactive.component_selection": "컴포넌트 선택",
    "interactive.service_selection": "서비스 선택",
    "interactive.core_included": ("코어 컴포넌트 ({components}) 자동 포함됨"),
    "interactive.infra_header": "인프라 컴포넌트:",
    "interactive.services_intro": (
        "서비스는 애플리케이션에 비즈니스 로직 기능을 제공합니다."
    ),
    # ── Component descriptions ──────────────────────────────────────────
    "component.backend": "FastAPI 백엔드 서버",
    "component.frontend": "Flet 프론트엔드 인터페이스",
    "component.redis": "Redis 캐시 및 메시지 브로커",
    "component.worker": "백그라운드 작업 처리 (arq, Dramatiq 또는 TaskIQ)",
    "component.scheduler": "예약 작업 실행 인프라",
    "component.database": "SQLModel ORM 데이터베이스 (SQLite 또는 PostgreSQL)",
    "component.ingress": "Traefik 리버스 프록시 및 로드 밸런서",
    "component.observability": "Logfire 관측성, 트레이싱 및 메트릭",
    "component.storage": "S3 object storage, SeaweedFS in dev",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Service descriptions ────────────────────────────────────────────
    "service.auth": "JWT 토큰 기반 사용자 인증 및 권한 부여",
    "service.ai": "멀티 프레임워크 지원 AI 챗봇 서비스",
    "service.comms": "이메일, SMS, 음성 통신 서비스",
    "service.documents": "Document store: keep the paper, deduped and findable",
    "service.blog": "초안, 게시, 태그 워크플로가 있는 Markdown 블로그",
    # ── Interactive: component prompts ─────────────────────────────────
    "interactive.add_prompt": "{description}을(를) 추가하시겠습니까?",
    "interactive.add_with_redis": "{description}을(를) 추가하시겠습니까? (Redis 자동 추가)",
    "interactive.worker_configured": "{backend} 백엔드 Worker 구성 완료",
    # ── Interactive: scheduler ─────────────────────────────────────────
    "interactive.scheduler_persistence": "스케줄러 영속성:",
    "interactive.persist_prompt": (
        "예약 작업을 영속화하시겠습니까? (작업 이력, 재시작 후 복구 활성화)"
    ),
    "interactive.scheduler_db_configured": "스케줄러 + {engine} 데이터베이스 구성 완료",
    "interactive.bonus_backup": "보너스: 데이터베이스 백업 작업 추가",
    "interactive.backup_desc": (
        "일일 데이터베이스 백업 예약 작업 포함 (매일 오전 2시 실행)"
    ),
    # ── Interactive: database engine ───────────────────────────────────
    "interactive.db_engine_label": "{context} 데이터베이스 엔진:",
    "interactive.db_select": "데이터베이스 엔진을 선택하세요:",
    "interactive.db_sqlite": "SQLite - 간단한 파일 기반 (개발용에 적합)",
    "interactive.db_postgres": ("PostgreSQL - 프로덕션용, 멀티 컨테이너 지원"),
    "interactive.db_reuse": "이전에 선택한 데이터베이스 사용: {engine}",
    "interactive.db_provider_select": "PostgreSQL 호스트 선택:",
    "interactive.db_provider_container": (
        "로컬 컨테이너 - Docker에서 실행되는 postgres:16 (개발 및 운영)"
    ),
    "interactive.db_provider_neon": (
        "Neon - 서버리스 Postgres (운영은 클라우드, 개발은 로컬 컨테이너)"
    ),
    # ── Interactive: worker backend ────────────────────────────────────
    "interactive.worker_label": "Worker 백엔드:",
    "interactive.worker_select": "Worker 백엔드를 선택하세요:",
    "interactive.worker_arq": "arq - 비동기, 경량 (기본값)",
    "interactive.worker_dramatiq": ("Dramatiq - 프로세스 기반, CPU 집약 작업에 적합"),
    "interactive.worker_taskiq": ("TaskIQ - 비동기, 프레임워크 스타일, 큐별 브로커"),
    # ── Interactive: auth ──────────────────────────────────────────────
    "interactive.auth_header": "인증 서비스:",
    "interactive.auth_level_label": "인증 수준:",
    "interactive.auth_select": "어떤 유형의 인증을 사용하시겠습니까?",
    "interactive.auth_basic": "기본 - 이메일/비밀번호 로그인",
    "interactive.auth_rbac": "역할 포함 - + 역할 기반 접근 제어 (실험적)",
    "interactive.auth_org": "조직 포함 - + 멀티 테넌트 지원 (실험적)",
    "interactive.auth_selected": "선택된 인증 수준: {level}",
    "interactive.auth_db_required": "데이터베이스 필요:",
    "interactive.auth_db_reason": (
        "인증에는 사용자 저장을 위한 데이터베이스가 필요합니다"
    ),
    "interactive.auth_db_details": "(사용자 계정, 세션, JWT 토큰)",
    "interactive.auth_db_already": "데이터베이스 컴포넌트 이미 선택됨",
    "interactive.auth_db_confirm": "계속하고 데이터베이스 컴포넌트를 추가하시겠습니까?",
    "interactive.auth_cancelled": "인증 서비스 취소됨",
    "interactive.auth_db_configured": "인증 + 데이터베이스 구성 완료",
    # ── Interactive: AI service ────────────────────────────────────────
    "interactive.ai_header": "AI 및 머신러닝 서비스:",
    "interactive.ai_framework_label": "AI 프레임워크 선택:",
    "interactive.ai_framework_intro": "AI 프레임워크를 선택하세요:",
    "interactive.ai_pydanticai": (
        "PydanticAI - 타입 안전, Pythonic AI 프레임워크 (권장)"
    ),
    "interactive.ai_langchain": ("LangChain - 광범위한 통합 지원의 인기 프레임워크"),
    "interactive.ai_use_pydanticai": "PydanticAI를 사용하시겠습니까? (권장)",
    "interactive.ai_selected_framework": "선택된 프레임워크: {framework}",
    "interactive.ai_tracking_context": "AI 사용량 추적",
    "interactive.ai_tracking_label": "LLM 사용량 추적:",
    "interactive.ai_tracking_prompt": (
        "사용량 추적을 활성화하시겠습니까? (토큰 수, 비용, 대화 이력)"
    ),
    "interactive.ai_sync_label": "LLM 카탈로그 동기화:",
    "interactive.ai_sync_desc": (
        "동기화는 OpenRouter/LiteLLM API에서 최신 모델 데이터를 가져옵니다"
    ),
    "interactive.ai_sync_time": ("네트워크 접속이 필요하며 약 30~60초 소요됩니다"),
    "interactive.ai_sync_prompt": "프로젝트 생성 시 LLM 카탈로그를 동기화하시겠습니까?",
    "interactive.ai_sync_will": "프로젝트 생성 후 LLM 카탈로그가 동기화됩니다",
    "interactive.ai_sync_skipped": ("LLM 동기화 건너뜀 - 정적 픽스처 데이터 사용 가능"),
    "interactive.ai_provider_label": "AI 제공자 선택:",
    "interactive.ai_provider_intro": ("포함할 AI 제공자를 선택하세요 (다중 선택 가능)"),
    "interactive.ai_provider_options": "제공자 옵션:",
    "interactive.ai_provider_recommended": "(권장)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI - GPT 모델 (유료)",
    "interactive.ai_provider.anthropic": "Anthropic - Claude 모델 (유료)",
    "interactive.ai_provider.google": "Google - Gemini 모델 (무료 티어)",
    "interactive.ai_provider.groq": "Groq - 고속 추론 (무료 티어)",
    "interactive.ai_provider.mistral": "Mistral - 오픈 모델 (대부분 유료)",
    "interactive.ai_provider.cohere": "Cohere - 기업용 (제한적 무료)",
    "interactive.ai_provider.ollama": "Ollama - 로컬 추론 (무료)",
    "interactive.ai_no_providers": (
        "제공자가 선택되지 않아 권장 기본값을 추가합니다..."
    ),
    "interactive.ai_selected_providers": "선택된 제공자: {providers}",
    "interactive.ai_deps_optimized": ("선택에 맞게 의존성이 최적화됩니다"),
    "interactive.ai_ollama_label": "Ollama 배포 모드:",
    "interactive.ai_ollama_intro": "Ollama를 어떻게 실행하시겠습니까?",
    "interactive.ai_ollama_host": ("호스트 - 로컬 머신의 Ollama에 연결 (Mac/Windows)"),
    "interactive.ai_ollama_docker": (
        "Docker - Docker 컨테이너에서 Ollama 실행 (Linux/배포)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "호스트 Ollama에 연결하시겠습니까? (Mac/Windows 권장)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama가 host.docker.internal:11434에 연결됩니다"
    ),
    "interactive.ai_ollama_host_hint": "Ollama가 실행 중인지 확인하세요: ollama serve",
    "interactive.ai_ollama_docker_ok": (
        "Ollama 서비스가 docker-compose.yml에 추가됩니다"
    ),
    "interactive.ai_ollama_docker_hint": (
        "참고: 첫 시작 시 모델 다운로드에 시간이 걸릴 수 있습니다"
    ),
    "interactive.ai_rag_label": "RAG (검색 증강 생성):",
    "interactive.ai_rag_prompt": (
        "문서 인덱싱 및 시맨틱 검색을 위해 RAG를 활성화하시겠습니까?"
    ),
    "interactive.ai_rag_enabled": "ChromaDB 벡터 스토어로 RAG 활성화됨",
    "interactive.ai_voice_label": "음성 (TTS 및 STT):",
    "interactive.ai_voice_prompt": (
        "음성 기능을 활성화하시겠습니까? (음성 상호작용을 위한 TTS 및 STT)"
    ),
    "interactive.ai_voice_enabled": "TTS 및 STT 지원 음성 활성화됨",
    "interactive.ai_db_already": "데이터베이스 이미 선택됨 - 사용량 추적 활성화됨",
    "interactive.ai_db_added": "사용량 추적을 위한 데이터베이스 ({backend}) 추가됨",
    "interactive.ai_configured": "AI 서비스 구성 완료",
    # ── Shared: validation ──────────────────────────────────────────────
    "shared.not_copier_project": "프로젝트 {path}은(는) Copier로 생성되지 않았습니다.",
    "shared.copier_only": (
        "'aegis {command}' 명령은 Copier로 생성된 프로젝트에서만 작동합니다."
    ),
    "shared.regenerate_hint": (
        "컴포넌트를 추가하려면 새 컴포넌트를 포함하여 프로젝트를 재생성하세요."
    ),
    "shared.git_not_initialized": "프로젝트가 git 저장소에 없습니다",
    "shared.git_required": "Copier 업데이트에는 변경 추적을 위한 git이 필요합니다",
    "shared.git_init_hint": (
        "'aegis init'으로 생성된 프로젝트는 git이 자동으로 초기화됩니다"
    ),
    "shared.git_manual_init": (
        "수동으로 생성한 프로젝트의 경우 다음을 실행하세요: "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "빈 컴포넌트 이름은 허용되지 않습니다",
    "shared.empty_service": "빈 서비스 이름은 허용되지 않습니다",
    # ── Shared: next steps / review ──────────────────────────────────
    "shared.next_steps": "다음 단계:",
    "shared.next_make_check": "   1. 'make check'를 실행하여 업데이트 확인",
    "shared.next_test": "   2. 애플리케이션 테스트",
    "shared.next_commit": "   3. 변경 사항 커밋: git add . && git commit",
    "shared.review_header": "변경 사항 검토:",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "작업 취소됨",
    "shared.interactive_ignores_args": (
        "경고: --interactive 플래그는 컴포넌트 인수를 무시합니다"
    ),
    "shared.no_components_selected": "선택된 컴포넌트 없음",
    "shared.no_services_selected": "선택된 서비스 없음",
    # ── Add command ──────────────────────────────────────────────────
    "add.title": "Aegis Stack - 컴포넌트 추가",
    "add.project": "프로젝트: {path}",
    "add.error_no_args": (
        "오류: components 인수가 필요합니다 (또는 --interactive 사용)"
    ),
    "add.usage_hint": "사용법: aegis add scheduler,worker",
    "add.interactive_hint": "또는: aegis add --interactive",
    "add.auto_added_deps": "자동 추가된 의존성: {deps}",
    "add.validation_failed": "컴포넌트 유효성 검사 실패: {error}",
    "add.load_config_failed": "프로젝트 구성 로드 실패: {error}",
    "add.already_enabled": "이미 활성화됨: {components}",
    "add.all_enabled": "요청한 모든 컴포넌트가 이미 활성화됨!",
    "add.components_to_add": "추가할 컴포넌트:",
    "add.scheduler_backend": "스케줄러 백엔드: {backend}",
    "add.confirm": "이 컴포넌트를 추가하시겠습니까?",
    "add.updating": "프로젝트 업데이트 중...",
    "add.adding": "{component} 추가 중...",
    "add.added_files": "{count}개 파일 추가 완료",
    "add.skipped_files": "{count}개 기존 파일 건너뜀",
    "add.success": "컴포넌트 추가 완료!",
    "add.failed_component": "{component} 추가 실패: {error}",
    "add.failed": "컴포넌트 추가 실패: {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "컴포넌트 형식 오류: {error}",
    "add.bracket_override": (
        "대괄호 구문 'scheduler[{engine}]'이(가) --backend {backend}을(를) 덮어씁니다"
    ),
    "add.invalid_scheduler_backend": "유효하지 않은 스케줄러 백엔드: '{backend}'",
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "유효한 옵션: {options}",
    "add.postgres_coming": "참고: PostgreSQL 지원은 향후 릴리스에서 추가 예정",
    "add.auto_added_db": "스케줄러 영속성을 위한 데이터베이스 컴포넌트 자동 추가됨",
    "add.generated_migration": "마이그레이션 생성됨: {name}",
    "add.scheduler_db_engine_mismatch": "스케줄러 백엔드 '{backend}'를 사용할 수 없습니다: 프로젝트의 데이터베이스 엔진이 '{engine}'입니다. 서로 일치해야 합니다.",
    # ── Remove command ────────────────────────────────────────────────
    "remove.title": "Aegis Stack - 컴포넌트 제거",
    "remove.project": "프로젝트: {path}",
    "remove.error_no_args": (
        "오류: components 인수가 필요합니다 (또는 --interactive 사용)"
    ),
    "remove.usage_hint": "사용법: aegis remove scheduler,worker",
    "remove.interactive_hint": "또는: aegis remove --interactive",
    "remove.no_selected": "제거할 컴포넌트가 선택되지 않음",
    "remove.validation_failed": "컴포넌트 유효성 검사 실패: {error}",
    "remove.load_config_failed": "프로젝트 구성 로드 실패: {error}",
    "remove.cannot_remove_core": "코어 컴포넌트 제거 불가: {component}",
    "remove.not_enabled": "활성화되지 않음: {components}",
    "remove.nothing_to_remove": "제거할 컴포넌트 없음!",
    "remove.auto_remove_redis": ("Redis 자동 제거 (단독 기능 없음, Worker에서만 사용)"),
    "remove.scheduler_persistence_warn": "중요: 스케줄러 영속성 경고",
    "remove.scheduler_persistence_detail": (
        "스케줄러가 작업 영속성에 SQLite를 사용합니다."
    ),
    "remove.scheduler_db_remains": (
        "data/scheduler.db의 데이터베이스 파일은 유지됩니다."
    ),
    "remove.scheduler_keep_hint": (
        "작업 이력을 보존하려면: 데이터베이스 컴포넌트를 유지하세요"
    ),
    "remove.scheduler_remove_hint": (
        "모든 데이터를 삭제하려면: 데이터베이스 컴포넌트도 제거하세요"
    ),
    "remove.components_to_remove": "제거할 컴포넌트:",
    "remove.warning_delete": ("경고: 프로젝트에서 컴포넌트 파일이 삭제됩니다!"),
    "remove.commit_hint": "git에 변경 사항을 커밋했는지 확인하세요.",
    "remove.confirm": "이 컴포넌트를 제거하시겠습니까?",
    "remove.removing_all": "컴포넌트 제거 중...",
    "remove.removing": "{component} 제거 중...",
    "remove.removed_files": "{count}개 파일 제거 완료",
    "remove.failed_component": "{component} 제거 실패: {error}",
    "remove.success": "컴포넌트 제거 완료!",
    "remove.failed": "컴포넌트 제거 실패: {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Manual updater ─────────────────────────────────────────────────
    "updater.processing_files": "{count}개 컴포넌트 파일 처리 중...",
    "updater.updating_shared": "공유 템플릿 파일 업데이트 중...",
    "updater.shared_preserved": "로컬 변경 사항을 보존했습니다 (재생성 건너뜀, 수동으로 병합하세요): {file}",
    "updater.shared_merged": "템플릿 변경 사항을 사용자 지정 파일에 병합했습니다: {file}",
    "updater.shared_conflict": "병합 충돌 (마커가 기록됨, 수동으로 해결하세요): {file}",
    "updater.running_postgen": "후처리 작업 실행 중...",
    "updater.deps_synced": "의존성 동기화 완료 (uv sync)",
    "updater.code_formatted": "코드 포맷팅 완료 (make fix)",
    # ── Project map ──────────────────────────────────────────────────
    "projectmap.new": "신규",
    # ── Post-generation: setup tasks ──────────────────────────────────
    "postgen.setup_start": "프로젝트 환경 설정 중...",
    "postgen.deps_installing": "uv로 의존성 설치 중...",
    "postgen.deps_success": "의존성 설치 완료",
    "postgen.deps_failed": "프로젝트 생성 실패: 의존성 설치 실패",
    "postgen.deps_failed_detail": (
        "생성된 프로젝트 파일은 남아 있지만 프로젝트를 사용할 수 없습니다."
    ),
    "postgen.deps_failed_hint": (
        "의존성 문제를 해결하고 (Python 버전 호환성 확인) 다시 시도하세요."
    ),
    "postgen.deps_warn_failed": "경고: 의존성 설치 실패",
    "postgen.deps_manual": "프로젝트 생성 후 'uv sync'를 수동으로 실행하세요",
    "postgen.deps_timeout": (
        "경고: 의존성 설치 시간 초과 - 'uv sync'를 수동으로 실행하세요"
    ),
    "postgen.deps_uv_missing": "경고: PATH에서 uv를 찾을 수 없음",
    "postgen.deps_uv_install": "먼저 uv를 설치하세요: https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "경고: 의존성 설치 실패: {error}",
    "postgen.env_setup": "환경 구성 설정 중...",
    "postgen.env_created": ".env.example에서 환경 파일 생성 완료",
    "postgen.env_exists": "환경 파일이 이미 존재합니다",
    "postgen.env_missing": "경고: .env.example 파일을 찾을 수 없음",
    "postgen.env_error": "경고: 환경 설정 실패: {error}",
    "postgen.env_manual": ".env.example을 .env로 수동 복사하세요",
    # ── Post-generation: database/migrations ────────────────────────────
    "postgen.db_setup": "데이터베이스 스키마 설정 중...",
    "postgen.db_success": "데이터베이스 테이블 생성 완료",
    "postgen.db_alembic_missing": "경고: {path}에 Alembic 설정 파일이 없음",
    "postgen.db_alembic_hint": (
        "데이터베이스 마이그레이션 건너뜀. 설정 파일이 존재하는지 확인 후 "
        "'alembic upgrade head'를 수동으로 실행하세요."
    ),
    "postgen.db_failed": "경고: 데이터베이스 마이그레이션 설정 실패",
    "postgen.db_manual": "프로젝트 생성 후 'alembic upgrade head'를 수동으로 실행하세요",
    "postgen.db_timeout": (
        "경고: 마이그레이션 설정 시간 초과 - 'alembic upgrade head'를 수동으로 실행하세요"
    ),
    "postgen.db_error": "경고: 마이그레이션 설정 실패: {error}",
    # ── Post-generation: LLM fixtures/sync ────────────────────────────
    "postgen.llm_seeding": "LLM 픽스처 시딩 중...",
    "postgen.llm_seed_success": "LLM 픽스처 시딩 완료",
    "postgen.llm_seed_failed": "경고: LLM 픽스처 시딩 실패",
    "postgen.llm_seed_manual": (
        "픽스처 로더를 실행하여 수동으로 픽스처를 시딩할 수 있습니다"
    ),
    "postgen.llm_seed_timeout": "경고: LLM 픽스처 시딩 시간 초과",
    "postgen.llm_seed_error": "경고: LLM 픽스처 시딩 실패: {error}",
    "postgen.llm_syncing": "외부 API에서 LLM 카탈로그 동기화 중...",
    "postgen.llm_sync_success": "LLM 카탈로그 동기화 완료",
    "postgen.llm_sync_failed": "경고: LLM 카탈로그 동기화 실패",
    "postgen.llm_sync_manual": (
        "'{slug} llm sync'를 수동으로 실행하여 카탈로그를 채우세요"
    ),
    "postgen.llm_sync_timeout": "경고: LLM 카탈로그 동기화 시간 초과",
    "postgen.llm_sync_error": "경고: LLM 카탈로그 동기화 실패: {error}",
    # ── Post-generation: formatting ───────────────────────────────────
    "postgen.format_timeout": (
        "경고: 포맷팅 시간 초과 - 'make fix'를 수동으로 실행하세요"
    ),
    "postgen.format_error": "경고: 자동 포맷팅 건너뜀: {error}",
    "postgen.format_error_manual": "'make fix'를 수동으로 실행하여 코드를 포맷하세요",
    "postgen.format_start": "생성된 코드 자동 포맷팅 중...",
    "postgen.format_success": "코드 포맷팅 완료",
    "postgen.format_partial": (
        "일부 포맷팅 문제가 감지되었지만 프로젝트는 정상 생성됨"
    ),
    "postgen.format_manual": "남은 문제를 해결하려면 'make fix'를 수동으로 실행하세요",
    "postgen.format_hint": "'make fix'를 실행하여 코드를 포맷하세요",
    "postgen.llm_sync_skipped": "LLM 카탈로그 동기화 건너뜀",
    "postgen.llm_fixtures_outdated": "정적 픽스처 데이터 로드됨 (오래된 데이터일 수 있음)",
    "postgen.llm_sync_hint": "최신 모델 데이터를 얻으려면 나중에 '{slug} llm sync'를 실행하세요",
    "postgen.llm_fixtures_fallback": (
        "정적 픽스처 데이터 사용 가능하지만 오래된 데이터일 수 있습니다"
    ),
    "postgen.ready": "프로젝트 실행 준비 완료!",
    "postgen.next_steps": "다음 단계:",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Overseer 열기: http://localhost:8000/dashboard/",
    # ── Post-generation: project map ──────────────────────────────────
    "projectmap.title": "프로젝트 구조:",
    "projectmap.components": "컴포넌트",
    "projectmap.services": "비즈니스 로직",
    "projectmap.models": "데이터베이스 모델",
    "projectmap.cli": "CLI 명령",
    "projectmap.entrypoints": "실행 대상",
    "projectmap.tests": "테스트 스위트",
    "projectmap.migrations": "마이그레이션",
    "projectmap.auth": "인증",
    "projectmap.ai": "AI 대화",
    "projectmap.comms": "통신",
    "projectmap.insights": "Adoption metrics",
    "projectmap.payment": "Payments and subscriptions",
    "projectmap.documents": "Document store",
    "projectmap.blog": "Markdown blog",
    "projectmap.finance": "Personal finance",
    "projectmap.docs": "문서",
    # ── Post-generation: footer ───────────────────────────────────────
    "postgen.docs_link": "문서: https://docs.aegis-stack.io",
    "postgen.star_prompt": ("Aegis Stack이 도움이 되었다면 별점을 남겨주세요:"),
    # ── Add-service command ────────────────────────────────────────────
    "add_service.title": "Aegis Stack - 서비스 추가",
    "add_service.project": "프로젝트: {path}",
    "add_service.error_no_args": (
        "오류: services 인수가 필요합니다 (또는 --interactive 사용)"
    ),
    "add_service.usage_hint": "사용법: aegis add-service auth,ai",
    "add_service.interactive_hint": "또는: aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "경고: --interactive 플래그는 서비스 인수를 무시합니다"
    ),
    "add_service.no_selected": "선택된 서비스 없음",
    "add_service.already_enabled": "이미 활성화됨: {services}",
    "add_service.all_enabled": "요청한 모든 서비스가 이미 활성화됨!",
    "add_service.validation_failed": "서비스 유효성 검사 실패: {error}",
    "add_service.load_config_failed": "프로젝트 구성 로드 실패: {error}",
    "add_service.services_to_add": "추가할 서비스:",
    "add_service.required_components": "필수 컴포넌트 (자동 추가됨):",
    "add_service.already_have_components": ("필수 컴포넌트 이미 보유: {components}"),
    "add_service.confirm": "이 서비스를 추가하시겠습니까?",
    "add_service.adding_component": "필수 컴포넌트 추가 중: {component}...",
    "add_service.failed_component": "컴포넌트 {component} 추가 실패: {error}",
    "add_service.added_files": "{count}개 파일 추가 완료",
    "add_service.skipped_files": "{count}개 기존 파일 건너뜀",
    "add_service.preserved_files": "{count}개의 공유 파일은 수동 검토가 필요합니다 (위 메시지 참조)",
    "add_service.adding_service": "서비스 추가 중: {service}...",
    "add_service.failed_service": "서비스 {service} 추가 실패: {error}",
    "add_service.resolve_failed": "서비스 의존성 해결 실패: {error}",
    "add_service.bootstrap_alembic": "Alembic 인프라 부트스트랩 중...",
    "add_service.created_file": "생성됨: {file}",
    "add_service.generated_migration": "마이그레이션 생성됨: {name}",
    "add_service.applying_migrations": "데이터베이스 마이그레이션 적용 중...",
    "add_service.migration_failed": (
        "경고: 자동 마이그레이션 실패. 'make migrate'를 수동으로 실행하세요."
    ),
    "add_service.success": "서비스 추가 완료!",
    "add_service.failed": "서비스 추가 실패: {error}",
    "add_service.auth_setup": "Auth 서비스 설정:",
    "add_service.auth_create_users": "   1. 테스트 사용자 생성: {cmd}",
    "add_service.auth_view_routes": "   2. 인증 라우트 확인: {url}",
    "add_service.ai_setup": "AI 서비스 설정:",
    "add_service.ai_set_provider": (
        "   1. .env에 {env_var} 설정 (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": "   2. 제공자 API 키 설정 ({env_var} 등)",
    "add_service.ai_test_cli": "   3. CLI로 테스트: {cmd}",
    # ── Remove-service command ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack - 서비스 제거",
    "remove_service.project": "프로젝트: {path}",
    "remove_service.error_no_args": (
        "오류: services 인수가 필요합니다 (또는 --interactive 사용)"
    ),
    "remove_service.usage_hint": "사용법: aegis remove-service auth,ai",
    "remove_service.interactive_hint": "또는: aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "경고: --interactive 플래그는 서비스 인수를 무시합니다"
    ),
    "remove_service.no_selected": "제거할 서비스가 선택되지 않음",
    "remove_service.not_enabled": "활성화되지 않음: {services}",
    "remove_service.nothing_to_remove": "제거할 서비스 없음!",
    "remove_service.validation_failed": "서비스 유효성 검사 실패: {error}",
    "remove_service.load_config_failed": ("프로젝트 구성 로드 실패: {error}"),
    "remove_service.services_to_remove": "제거할 서비스:",
    "remove_service.auth_warning": "중요: Auth 서비스 경고",
    "remove_service.auth_delete_intro": "Auth 서비스를 제거하면 다음이 삭제됩니다:",
    "remove_service.auth_delete_endpoints": "사용자 인증 API 엔드포인트",
    "remove_service.auth_delete_models": "사용자 모델 및 인증 서비스",
    "remove_service.auth_delete_jwt": "JWT 토큰 처리 코드",
    "remove_service.auth_db_note": (
        "참고: 데이터베이스 테이블과 Alembic 마이그레이션은 삭제되지 않습니다."
    ),
    "remove_service.warning_delete": ("경고: 프로젝트에서 서비스 파일이 삭제됩니다!"),
    "remove_service.confirm": "이 서비스를 제거하시겠습니까?",
    "remove_service.removing": "서비스 제거 중: {service}...",
    "remove_service.failed_service": "서비스 {service} 제거 실패: {error}",
    "remove_service.removed_files": "{count}개 파일 제거 완료",
    "remove_service.success": "서비스 제거 완료!",
    "remove_service.failed": "서비스 제거 실패: {error}",
    "remove_service.deps_not_removed": (
        "참고: 서비스 의존성 (데이터베이스 등)은 제거되지 않았습니다."
    ),
    "remove_service.deps_remove_hint": (
        "'aegis remove <component>'로 컴포넌트를 별도로 제거하세요."
    ),
    # ── Version command ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Components command ─────────────────────────────────────────────
    "components.core_title": "코어 컴포넌트",
    "components.backend_desc": ("  backend      - FastAPI 백엔드 서버 (항상 포함)"),
    "components.frontend_desc": (
        "  frontend     - Flet 프론트엔드 인터페이스 (항상 포함)"
    ),
    "components.infra_title": "인프라 컴포넌트",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "필수: {deps}",
    "components.recommends": "권장: {deps}",
    "components.usage_hint": (
        "'aegis init PROJECT_NAME --components redis,worker'로 컴포넌트를 선택하세요"
    ),
    # ── Services command ───────────────────────────────────────────────
    "services.title": "사용 가능한 서비스",
    "services.type_auth": "인증 서비스",
    "services.type_payment": "결제 서비스",
    "services.type_ai": "AI 및 머신러닝 서비스",
    "services.type_notification": "알림 서비스",
    "services.type_analytics": "분석 서비스",
    "services.type_storage": "스토리지 서비스",
    "services.type_content": "콘텐츠 서비스",
    "services.type_finance": "금융 서비스",
    "services.requires_components": "필수 컴포넌트: {deps}",
    "services.recommends_components": "권장 컴포넌트: {deps}",
    "services.requires_services": "필수 서비스: {deps}",
    "services.none_available": "  아직 사용 가능한 서비스가 없습니다.",
    "services.usage_hint": (
        "'aegis init PROJECT_NAME --services auth'로 서비스를 추가하세요"
    ),
    # ── Update command ─────────────────────────────────────────────────
    "update.title": "Aegis Stack - 템플릿 업데이트",
    "update.not_copier": "프로젝트 {path}은(는) Copier로 생성되지 않았습니다.",
    "update.copier_only": (
        "'aegis update' 명령은 Copier로 생성된 프로젝트에서만 작동합니다."
    ),
    "update.need_regen": "v0.2.0 이전에 생성된 프로젝트는 재생성이 필요합니다.",
    "update.project": "프로젝트: {path}",
    "update.commit_or_stash": (
        "'aegis update' 실행 전에 변경 사항을 커밋하거나 스태시하세요."
    ),
    "update.clean_required": (
        "Copier가 안전하게 변경 사항을 병합하려면 깨끗한 git 트리가 필요합니다."
    ),
    "update.git_clean": "git 트리 깨끗함",
    "update.dirty_tree": "git 트리에 커밋되지 않은 변경 사항 있음",
    "update.changelog_breaking": "주요 변경 사항:",
    "update.changelog_features": "새로운 기능:",
    "update.changelog_fixes": "버그 수정:",
    "update.changelog_other": "기타 변경 사항:",
    "update.current_commit": "   현재: {commit}...",
    "update.target_commit": "   대상: {commit}...",
    "update.unknown_version": "경고: 현재 템플릿 버전을 확인할 수 없음",
    "update.untagged_commit": (
        "프로젝트가 태그되지 않은 커밋에서 생성되었을 수 있습니다"
    ),
    "update.custom_template": "커스텀 템플릿 사용 ({source}): {path}",
    "update.version_info": "버전 정보:",
    "update.current_cli": "   현재 CLI:      {version}",
    "update.current_template": "   현재 템플릿: {version}",
    "update.current_template_commit": "   현재 템플릿: {commit}... (커밋)",
    "update.current_template_unknown": "   현재 템플릿: 알 수 없음",
    "update.target_template": "   대상 템플릿:  {version}",
    "update.already_at_version": "프로젝트가 이미 요청한 버전입니다",
    "update.already_at_commit": "프로젝트가 이미 대상 커밋에 있습니다",
    "update.ahead_of_target": ("프로젝트가 대상 템플릿 버전보다 최신입니다"),
    "update.ahead_of_target_hint": (
        "업데이트할 항목이 없습니다. 특정 버전을 지정하려면 --to-version 옵션을 사용하세요."
    ),
    "update.downgrade_blocked": "다운그레이드 불가",
    "update.downgrade_reason": (
        "Copier는 이전 템플릿 버전으로의 다운그레이드를 지원하지 않습니다."
    ),
    "update.changelog": "변경 로그:",
    "update.dry_run": "드라이 런 모드 - 변경 사항이 적용되지 않습니다",
    "update.dry_run_hint": "이 업데이트를 적용하려면 다음을 실행하세요:",
    "update.confirm": "이 업데이트를 적용하시겠습니까?",
    "update.cancelled": "업데이트 취소됨",
    "update.creating_backup": "백업 포인트 생성 중...",
    "update.backup_created": "   백업 생성 완료: {tag}",
    "update.backup_failed": "백업 포인트를 생성할 수 없음",
    "update.updating": "프로젝트 업데이트 중...",
    "update.updating_to": "템플릿 버전 {version}으로 업데이트 중",
    "update.moved_files": "   중첩 디렉토리에서 {count}개 새 파일 이동 완료",
    "update.synced_files": "   {count}개 템플릿 변경 사항 동기화 완료",
    "update.merge_conflicts": (
        "   {count}개 파일에 병합 충돌 있음 (<<<<<<< 검색으로 해결):"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "후처리 작업 실행 중...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": "   __aegis_version__을 {version}으로 업데이트 완료",
    "update.success": "업데이트 완료!",
    "update.partial_success": ("업데이트 완료 (일부 후처리 작업 실패)"),
    "update.partial_detail": "   일부 설정 작업이 실패했습니다. 위 세부 사항을 확인하세요.",
    "update.next_steps": "다음 단계:",
    "update.next_review": "   1. 변경 사항 검토: git diff",
    "update.next_conflicts": "   2. 충돌 확인 (*.rej 파일)",
    "update.next_test": "   3. 테스트 실행: make check",
    "update.next_commit": "   4. 변경 사항 커밋: git add . && git commit",
    "update.failed": "업데이트 실패: {error}",
    "update.rollback_prompt": "이전 상태로 롤백하시겠습니까?",
    "update.manual_rollback": "수동 롤백: git reset --hard {tag}",
    "update.troubleshooting": "문제 해결:",
    "update.troubleshoot_clean": "   - 깨끗한 git 트리인지 확인하세요",
    "update.troubleshoot_version": "   - 버전/커밋이 존재하는지 확인하세요",
    "update.troubleshoot_docs": "   - 업데이트 문제는 Copier 문서를 참조하세요",
    # ── Ingress command ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack - Ingress TLS 활성화",
    "ingress.project": "프로젝트: {path}",
    "ingress.not_found": "Ingress 컴포넌트를 찾을 수 없음. 먼저 추가합니다...",
    "ingress.add_confirm": "Ingress 컴포넌트를 추가하시겠습니까?",
    "ingress.add_failed": "Ingress 컴포넌트 추가 실패: {error}",
    "ingress.added": "Ingress 컴포넌트 추가 완료.",
    "ingress.tls_already": "이 프로젝트에 TLS가 이미 활성화됨.",
    "ingress.domain_label": "   도메인: {domain}",
    "ingress.acme_email": "   ACME 이메일: {email}",
    "ingress.domain_prompt": (
        "도메인 이름 (예: example.com, IP 기반 라우팅은 비워두세요)"
    ),
    "ingress.email_reuse": "기존 ACME 이메일 사용: {email}",
    "ingress.email_prompt": "Let's Encrypt 알림용 이메일",
    "ingress.email_required": ("오류: TLS에 --email 필수 (Let's Encrypt에 필요)"),
    "ingress.tls_config": "TLS 구성:",
    "ingress.domain_none": "   도메인: (없음 - IP/PathPrefix 라우팅)",
    "ingress.tls_confirm": "이 구성으로 TLS를 활성화하시겠습니까?",
    "ingress.enabling": "TLS 활성화 중...",
    "ingress.updated_file": "   업데이트됨: {file}",
    "ingress.created_file": "   생성됨: {file}",
    "ingress.success": "TLS 활성화 완료!",
    "ingress.available_at": "   앱 접속 주소: https://{domain}",
    "ingress.https_configured": "   Let's Encrypt로 HTTPS 구성 완료",
    "ingress.next_steps": "다음 단계:",
    "ingress.next_deploy": "   1. 배포: aegis deploy",
    "ingress.next_ports": "   2. 서버에서 80, 443 포트가 열려 있는지 확인",
    "ingress.next_dns": ("   3. {domain}의 DNS A 레코드를 서버 IP로 설정"),
    "ingress.next_certs": "   인증서는 첫 요청 시 자동 발급됩니다",
    # ── Deploy commands ────────────────────────────────────────────────
    "deploy.no_config": (
        "배포 구성을 찾을 수 없음. 먼저 'aegis deploy-init'을 실행하세요."
    ),
    "deploy.init_saved": "배포 구성 저장 완료: {file}",
    "deploy.init_host": "   호스트: {host}",
    "deploy.init_user": "   사용자: {user}",
    "deploy.init_path": "   경로: {path}",
    "deploy.init_docker_context": "   Docker 컨텍스트: {context}",
    "deploy.prompt_host": "서버 IP 또는 호스트명",
    "deploy.init_gitignore": (
        "참고: 배포 구성 커밋 방지를 위해 .aegis/를 .gitignore에 추가하세요"
    ),
    "deploy.setup_title": "{target} 서버 설정 중...",
    "deploy.checking_ssh": "SSH 연결 확인 중...",
    "deploy.adding_host_key": "서버를 known_hosts에 추가 중...",
    "deploy.ssh_keyscan_failed": "SSH 호스트 키 스캔 실패: {error}",
    "deploy.ssh_failed": "SSH 연결 실패: {error}",
    "deploy.copying_script": "서버에 설정 스크립트 복사 중...",
    "deploy.copy_failed": "설정 스크립트 복사 실패",
    "deploy.running_setup": "서버 설정 실행 중 (몇 분 소요될 수 있음)...",
    "deploy.setup_failed": "서버 설정 실패",
    "deploy.setup_script_missing": "서버 설정 스크립트를 찾을 수 없음: {path}",
    "deploy.setup_script_hint": (
        "프로젝트가 ingress 컴포넌트로 생성되었는지 확인하세요."
    ),
    "deploy.setup_complete": "서버 설정 완료!",
    "deploy.setup_verify": "설치 확인:",
    "deploy.setup_verify_docker": "  Docker: {version}",
    "deploy.setup_verify_compose": "  Docker Compose: {version}",
    "deploy.setup_verify_uv": "  uv: {version}",
    "deploy.setup_verify_app_dir": "  앱 디렉토리: {path}",
    "deploy.setup_next": "다음: 'aegis deploy'를 실행하여 애플리케이션을 배포하세요",
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
    "deploy.deploying": "{host}에 배포 중...",
    "deploy.creating_backup": "백업 생성 중 {timestamp}...",
    "deploy.backup_failed": "백업 생성 실패: {error}",
    "deploy.backup_db": "PostgreSQL 데이터베이스 백업 중...",
    "deploy.backup_db_neon": "데이터베이스는 Neon이 관리합니다(브랜치 / 특정 시점 복원). 로컬 백업을 건너뜁니다",
    "deploy.backup_db_failed": ("경고: 데이터베이스 백업 실패, 백업 없이 계속 진행"),
    "deploy.backup_created": "백업 생성 완료: {timestamp}",
    "deploy.backup_pruned": "오래된 백업 정리됨: {name}",
    "deploy.no_existing": "기존 배포를 찾을 수 없음, 백업 건너뜀",
    "deploy.syncing": "서버에 파일 동기화 중...",
    "deploy.mkdir_failed": "원격 디렉토리 '{path}' 생성 실패",
    "deploy.sync_failed": "파일 동기화 실패",
    "deploy.copying_env": "{file}을(를) 서버에 .env로 복사 중...",
    "deploy.env_copy_failed": ".env 파일 복사 실패",
    "deploy.stopping": "기존 서비스 중지 중...",
    "deploy.building": "서버에서 서비스 빌드 및 시작 중...",
    "deploy.start_failed": "서비스 시작 실패",
    "deploy.auto_rollback": "이전 버전으로 자동 롤백 중...",
    "deploy.health_waiting": "컨테이너 안정화 대기 중...",
    "deploy.health_attempt": "헬스 체크 시도 {n}/{total}...",
    "deploy.health_passed": "헬스 체크 통과",
    "deploy.health_retry": "헬스 체크 실패, {interval}초 후 재시도...",
    "deploy.health_all_failed": "모든 헬스 체크 시도 실패",
    "deploy.rolled_back": "백업 {timestamp}으로 롤백 완료",
    "deploy.rollback_failed": "롤백 실패! 수동 조치가 필요합니다.",
    "deploy.health_failed_hint": (
        "배포 완료되었지만 헬스 체크 실패. 로그 확인: aegis deploy-logs"
    ),
    "deploy.complete": "배포 완료!",
    "deploy.rolling_starting": "{host}에 롤링 배포 중...",
    "deploy.rolling_building": "웹서버 이미지 빌드 중...",
    "deploy.rolling_pausing": "워커 큐 일시중지 중...",
    "deploy.rolling_pause_failed": (
        "일시중지 플래그를 설정하지 못했습니다. 워커가 작업 도중 SIGTERM될 수 있습니다."
    ),
    "deploy.rolling_draining": ("워커 드레인을 최대 {seconds}초 대기 중..."),
    "deploy.rolling_drain_timeout": (
        "워커가 시간 내에 드레인되지 않았습니다. 일시중지 플래그를 해제하고 중단합니다."
    ),
    "deploy.rolling_recreating": "재생성: {services}",
    "deploy.rolling_webserver": (
        "웹서버 롤링 재시작 중(정상 상태까지 최대 {seconds}초 대기)..."
    ),
    "deploy.rolling_rollout_failed": (
        "docker rollout 실패. 배포 호스트의 ~/.docker/cli-plugins/에 "
        "플러그인이 설치되어 있나요?"
    ),
    "deploy.rolling_complete": "롤링 배포 완료!",
    "deploy.app_running": "   애플리케이션 실행 중: http://{host}",
    "deploy.overseer": "   Overseer 대시보드: http://{host}/dashboard/",
    "deploy.view_logs": "   로그 확인: aegis deploy-logs",
    "deploy.check_status": "   상태 확인: aegis deploy-status",
    "deploy.backup_complete": "백업 완료!",
    "deploy.creating_backup_on": "{host}에서 백업 생성 중...",
    "deploy.no_backups": "백업을 찾을 수 없음.",
    "deploy.backups_header": "{host}의 백업 ({count}개):",
    "deploy.col_timestamp": "타임스탬프",
    "deploy.col_size": "크기",
    "deploy.col_database": "데이터베이스",
    "deploy.rollback_hint": ("롤백: aegis deploy-rollback --backup <timestamp>"),
    "deploy.no_backups_available": "사용 가능한 백업 없음.",
    "deploy.rolling_back": "{host}에서 백업 {backup}으로 롤백 중...",
    "deploy.rollback_not_found": "백업을 찾을 수 없음: {timestamp}",
    "deploy.rollback_stopping": "서비스 중지 중...",
    "deploy.rollback_restoring": "백업 {timestamp}에서 파일 복원 중...",
    "deploy.rollback_restore_failed": "파일 복원 실패: {error}",
    "deploy.rollback_db": "데이터베이스 복원 중...",
    "deploy.rollback_db_neon": "데이터베이스 복구는 Neon이 관리합니다(브랜치 / 특정 시점 복원). 로컬 복원을 건너뜁니다",
    "deploy.rollback_pg_wait": "PostgreSQL 준비 대기 중...",
    "deploy.rollback_pg_timeout": ("PostgreSQL이 준비되지 않았지만 복원을 시도합니다"),
    "deploy.rollback_db_failed": "경고: 데이터베이스 복원 실패",
    "deploy.rollback_starting": "서비스 시작 중...",
    "deploy.rollback_start_failed": "롤백 후 서비스 시작 실패",
    "deploy.rollback_complete": "롤백 완료!",
    "deploy.rollback_failed_final": "롤백 실패!",
    "deploy.status_header": "{host}의 서비스 상태:",
    "deploy.stop_stopping": "서비스 중지 중...",
    "deploy.stop_success": "서비스 중지 완료",
    "deploy.stop_failed": "서비스 중지 실패",
    "deploy.restart_restarting": "서비스 재시작 중...",
    "deploy.restart_success": "서비스 재시작 완료",
    "deploy.restart_failed": "서비스 재시작 실패",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": "Aegis Stack 프로젝트 경로 (기본값: 현재 디렉토리)",
    "common.help_project_path": "프로젝트 경로 (기본값: 현재 디렉토리)",
    "common.help_yes": "확인 생략",
    "common.help_yes_plural": "모든 확인 생략",
    "common.help_interactive_components": "대화형 컴포넌트 선택",
    "common.help_interactive_services": "대화형 서비스 선택",
    "common.help_force": "버전 불일치 경고를 무시하고 강제로 진행",
    # ── init CLI help ──────────────────────────────────────────────────
    "blueprints.title": "AVAILABLE BLUEPRINTS",
    "blueprints.none_available": "No blueprints available.",
    "blueprints.includes": "Includes: {names}",
    "blueprints.usage_hint": "Start a project from one:",
    "init.help_opt_blueprint": (
        "Start from a named blueprint (a preset component/service selection)"
    ),
    "init.unknown_blueprint": "Unknown blueprint: {name}. Available: {available}",
    "init.help_arg_name": "새로 생성할 Aegis Stack 프로젝트 이름",
    "init.help_opt_components": "쉼표로 구분된 컴포넌트 목록 (redis, worker, scheduler, database)",
    "init.help_opt_python": "생성되는 프로젝트의 Python 버전 (3.11, 3.12, 3.13 또는 3.14)",
    "init.help_opt_force": "디렉토리가 이미 있으면 덮어쓰기",
    "init.help_opt_directory": "프로젝트를 생성할 디렉토리 (기본값: 현재 디렉토리)",
    "init.help_opt_template_version": "지정한 템플릿 버전으로부터 생성 (태그, 커밋 또는 브랜치)",
    "init.help_opt_no_llm_sync": "프로젝트 생성 후 LLM 카탈로그 동기화를 건너뜀 (AI 서비스에만 해당)",
    "init.help_opt_dev": "개발 모드: 작업 트리에서 템플릿을 읽음 (커밋되지 않은 변경 포함)",
    "init.help_opt_services": "서비스: {services}. AI 옵션: ai[framework,backend,providers] (framework={frameworks}, backend={backends}, providers={providers})",
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": "추가할 컴포넌트 목록, 쉼표로 구분 (scheduler, worker, database)",
    "add.help_opt_scheduler_backend": "스케줄러 백엔드: 'memory' (기본값) 또는 'sqlite' (영속성 활성화)",
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "지정한 버전으로 업데이트 (기본값: 최신)",
    "update.help_opt_dry_run": "변경 사항을 적용하지 않고 미리 보기만 실행",
    "update.help_opt_template_path": "설치된 버전 대신 사용자 지정 템플릿 경로 사용",
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": "제거할 컴포넌트 목록, 쉼표로 구분 (scheduler, worker, database)",
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": "추가할 서비스 목록, 쉼표로 구분 (auth, ai)",
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": "제거할 서비스 목록, 쉼표로 구분 (auth, ai, comms)",
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": "TLS 인증서에 사용할 도메인 이름 (예: example.com)",
    "ingress.help_opt_email": "Let's Encrypt 인증서 알림을 받을 이메일 주소",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "서버 IP 주소 또는 호스트명",
    "deploy.help_opt_user": "배포에 사용할 SSH 사용자",
    "deploy.help_opt_path": "서버상의 배포 경로",
    "deploy.help_opt_public_key": "배포 사용자 authorized_keys에 추가할 공개 키 경로 (멱등 작업). 이 옵션을 사용하면 배포 전에 ssh-copy-id를 직접 실행할 필요가 없습니다.",
    "deploy.help_opt_build": "배포 전에 이미지를 빌드",
    "deploy.help_opt_backup": "배포 전에 백업 생성",
    "deploy.help_opt_health": "배포 후 헬스 체크 실행",
    "deploy.help_opt_rolling": (
        "HTTP 다운타임 없는 코드 전용 배포. docker-rollout으로 "
        "웹서버를 롤링하고 워커 큐를 일시중지해 진행 중인 작업이 "
        "안전하게 완료되도록 합니다. DB 마이그레이션은 건너뜁니다."
    ),
    "deploy.help_opt_drain_timeout": (
        "롤링 배포 시 큐를 일시중지한 후 워커가 드레인될 때까지 "
        "기다리는 시간(초). 기본값: 90."
    ),
    "deploy.help_opt_rollout_timeout": (
        "롤링 배포 시 docker-rollout이 새 웹서버가 정상 상태가 될 때까지 "
        "기다리는 시간(초). 60초 고정값이 아니라 컨테이너의 HEALTHCHECK "
        "예산(start_period + retries × interval)에 맞춰 설정하세요. "
        "기본값: 900."
    ),
    "deploy.help_opt_rollback_backup": "롤백할 백업의 타임스탬프 (기본값: 가장 최근)",
    "deploy.help_opt_logs_follow": "로그 출력을 계속 따라가며 표시",
    "deploy.help_opt_logs_service": "특정 서비스의 로그만 표시",
    "deploy.help_opt_shell_service": "접속할 서비스",
    "deploy.help_opt_gh_repo": "GitHub 저장소 (owner/name 형식, 기본값: git remote origin에서 자동 감지)",
    "deploy.help_opt_gh_tags": "v* 태그 푸시 시에도 배포 워크플로 실행",
    "deploy.help_opt_gh_overwrite": "기존 GitHub Secrets와 deploy.yml 워크플로 덮어쓰기",
    "deploy.help_opt_dry_run": "실제 변경 없이 예정된 작업만 출력",
    "deploy.help_opt_local_key_path": "정리 전에 생성된 개인 키를 복사해 둘 경로. 기본값: 로컬 복사본 없음 (키는 GitHub Secrets에만 저장).",
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "설치된 Aegis 플러그인 확인 및 레지스트리 검색",
    "plugins.cannot_read_answers": "{path}을(를) 읽을 수 없습니다: {error}. 호환성 검사를 건너뜁니다.",
    "plugins.help_list": "설치된 플러그인과 이 프로젝트와의 호환성을 나열합니다.",
    "plugins.help_opt_list_project_path": "호환성을 평가할 대상 프로젝트 (Aegis 프로젝트라면 기본값은 현재 디렉토리).",
    "plugins.help_opt_list_verbose": "설명 컬럼 표시.",
    "plugins.section_in_tree": "내장 (공식)",
    "plugins.section_external": "외부 플러그인",
    "plugins.col_name": "이름",
    "plugins.col_version": "버전",
    "plugins.col_kind": "종류",
    "plugins.col_description": "설명",
    "plugins.col_status": "상태",
    "plugins.no_external_installed": "설치된 외부 플러그인이 없습니다. 다음으로 설치할 수 있습니다: pip install aegis-plugin-<name>",
    "plugins.help_info": "단일 플러그인의 상세 정보를 표시합니다.",
    "plugins.help_arg_info_name": "플러그인 이름 (예: 'auth', 'scraper')",
    "plugins.help_opt_info_project_path": "호환성을 평가할 대상 프로젝트.",
    "plugins.not_installed_named": "'{name}'이라는 이름의 플러그인이 설치되어 있지 않습니다.",
    "plugins.available_list": "사용 가능: {names}",
    "plugins.label_first_party": "(공식)",
    "plugins.label_verified": "(검증됨)",
    "plugins.label_unverified": "(커뮤니티, 미검증)",
    "plugins.label_kind": "종류:",
    "plugins.label_type": "하위 유형:",
    "plugins.label_requires_components": "필요 컴포넌트:",
    "plugins.label_recommends_components": "권장 컴포넌트:",
    "plugins.label_requires_services": "필요 서비스:",
    "plugins.label_requires_plugins": "필요 플러그인:",
    "plugins.label_conflicts": "충돌:",
    "plugins.label_python_deps": "Python 의존성:",
    "plugins.deps_more": "(외 {count}개)",
    "plugins.section_options": "옵션",
    "plugins.option_choices": "선택지:",
    "plugins.option_default": "기본값:",
    "plugins.option_auto_requires": "(auto_requires 포함)",
    "plugins.info_files": "파일: {files}   마이그레이션: {migrations}개 ({tables}개 테이블)   CLI: {cli}",
    "plugins.cli_yes": "예",
    "plugins.cli_no": "아니오",
    "plugins.section_compat": "호환성",
    "plugins.help_update": "설치된 플러그인의 템플릿을 현재 pip로 설치된 버전 기준으로 다시 렌더링합니다.",
    "plugins.help_arg_update_name": "업데이트할 플러그인. --all을 지정하지 않으면 필수입니다.",
    "plugins.help_opt_update_all": "이 프로젝트의 _plugins에 등록된 모든 플러그인을 업데이트합니다.",
    "plugins.help_opt_update_force": "새 플러그인 버전의 aegis_version 제약이 현재 CLI를 제외해도 업데이트를 적용합니다.",
    "plugins.update_need_target": "플러그인 이름을 지정하거나 --all을 사용하세요.",
    "plugins.update_either_not_both": "플러그인 이름 또는 --all 중 하나만 전달하세요 (둘 다 사용 불가).",
    "plugins.update_no_plugins_installed": "이 프로젝트에는 설치된 플러그인이 없습니다.",
    "plugins.update_not_in_project": "플러그인 '{name}'은(는) 이 프로젝트에 설치되어 있지 않습니다.",
    "plugins.update_use_list_hint": "사용 가능한 플러그인은 `aegis plugins list`로 확인하고, `aegis add <name>`로 설치하세요.",
    "plugins.update_not_pip_installed": "플러그인 '{name}'은(는) 프로젝트의 _plugins 목록에 있지만 pip로 설치되어 있지 않습니다. 먼저 `pip install aegis-plugin-{name}`을 실행하세요.",
    "plugins.update_already_at": "{name} (이미 {version})",
    "plugins.local_changes_replaced": (
        "Replaced {count} locally-modified file(s) owned by '{name}'. "
        "Plugin files are re-rendered on install; your previous versions "
        "were saved to {path}"
    ),
    "plugins.update_forcing": "버전 불일치를 무시하고 강제 업데이트: {error}",
    "plugins.update_progress": "플러그인 업데이트 중: {name} ({old} → {new})",
    "plugins.update_confirm_apply": "'{name}'에 업데이트를 적용하시겠습니까?",
    "plugins.update_skipped_by_user": "{name} (사용자가 건너뜀)",
    "plugins.update_legacy_strings": "문자열 형식의 레거시 _plugins 항목을 건너뜁니다: {entries}. `aegis add <name>`으로 다시 추가하여 현재의 dict 형식으로 마이그레이션하세요.",
    "plugins.update_summary_updated": "업데이트됨: {count}",
    "plugins.update_summary_skipped": "건너뜀: {count}",
    "plugins.update_summary_failed": "실패: {count}",
    "plugins.help_create": "새로운 aegis-plugin-<name> Python 패키지의 스캐폴드를 생성합니다.",
    "plugins.help_arg_create_name": "플러그인 이름 (소문자, 하이픈 없음). Python 패키지 이름 aegis_plugin_<name> 및 설치 이름 aegis-plugin-<name>으로 사용됩니다.",
    "plugins.help_opt_create_target": "플러그인 스캐폴드가 생성될 상위 디렉토리.",
    "plugins.help_opt_create_author": "pyproject.toml 및 README에 사용할 작성자 정보.",
    "plugins.help_opt_create_description": "한 줄짜리 플러그인 설명.",
    "plugins.create_target_missing": "대상 디렉토리가 존재하지 않습니다: {target}",
    "plugins.create_already_exists": "디렉토리가 이미 존재합니다: {output}",
    "plugins.create_pick_different": "다른 이름을 선택하거나 기존 디렉토리를 제거하세요.",
    "plugins.create_starting": "플러그인 생성 중: {name}",
    "plugins.create_label_target": "대상:",
    "plugins.create_label_author": "작성자:",
    "plugins.create_label_description": "설명:",
    "plugins.create_default_marker": "(기본값)",
    "plugins.create_confirm": "스캐폴드를 생성하시겠습니까?",
    "plugins.create_cancelled": "취소되었습니다.",
    "plugins.create_success": "{output} 아래에 {count}개의 파일을 생성했습니다",
    "plugins.create_next_steps_header": "다음 단계:",
    "plugins.create_next_steps_confirm_comment": "플러그인이 감지되는지 확인",
    "plugins.create_next_steps_edit_comment": "src/aegis_plugin_<name>/plugin.py를 편집해 와이어링 추가",
    "plugins.help_search": "공식 플러그인 레지스트리를 검색합니다.",
    "plugins.help_arg_search_keyword": "검색할 키워드 (선택)",
    "plugins.search_not_available": "플러그인 레지스트리는 아직 사용할 수 없습니다.",
    "plugins.search_install_hint": "현재 방식: pip install aegis-plugin-<name>을 실행한 다음 aegis plugins list.",
    "plugins.search_future_keyword": "레지스트리가 가동되면 이 명령은 '{keyword}'을(를) 검색합니다.",
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "첫날부터 프로덕션에 바로 쓸 수 있는 Python 앱.",
    "guided.welcome.body": "이 가이드 설정은 각 구성 요소를 간단한 설명과 함께 차례로 안내하여 프로젝트에 필요한 것을 결정하도록 돕습니다. 지금은 원하는 것만 선택하세요. 나머지는 나중에 'aegis add'로 추가할 수 있습니다.",
    "guided.corestack.title": "모든 프로젝트에 포함됨",
    "guided.corestack.body": "모든 Aegis 프로젝트는 이 둘로 시작하며, 서로 연결되어 바로 실행할 수 있습니다.",
    "guided.sidebar.components": "컴포넌트",
    "guided.sidebar.services": "서비스",
    "guided.prompt.worker_backend": "워커 백엔드 선택",
    "guided.prompt.scheduler_backend": "스케줄러 영속성: 재시작 후에도 작업 기록을 유지할까요?",
    "guided.prompt.database_engine": "{context}의 데이터베이스 엔진",
    "guided.prompt.postgres_provider": "{context}의 PostgreSQL 호스트",
    "guided.prompt.auth_level": "인증 수준",
    "guided.prompt.ai_framework": "AI 프레임워크",
    "guided.prompt.ai_providers": "AI 제공자: 연동할 항목을 선택하세요",
    "guided.prompt.ai_storage": "AI 대화 저장",
    "guided.prompt.ai_rag": "RAG 추가: 직접 만든 문서와 코드를 기반으로 대화할까요?",
    "guided.prompt.ai_voice": "음성 추가: 텍스트 음성 변환과 음성 인식?",
    "guided.note.one_datastore": "데이터 저장소는 프로젝트당 하나: 여기서 선택한 엔진이 프로젝트 데이터베이스가 되며, 데이터를 저장하는 다른 모든 기능이 이를 공유합니다.",
    "guided.note.one_database_host": "데이터베이스는 프로젝트당 하나: 데이터를 저장하는 모든 기능이 이 호스트를 사용합니다.",
    "guided.multi.hint": "원하는 만큼 선택한 다음 '계속'을 선택하세요.",
    "guided.choice.add": "추가",
    "guided.choice.skip": "건너뛰기",
    "guided.screen.add_question": "{name} 추가할까요?",
    "guided.screen.too_small": "터미널이 너무 작습니다. 최소 {w}x{h}로 조정하세요.",
    "guided.review.title": "프로젝트 구성",
    "guided.review.files_pane": "컴포넌트 파일",
    "guided.review.deps_pane": "의존성",
    "guided.review.counts": "컴포넌트 파일 {files}개 · 의존성 {deps}개",
    "guided.building.title": "{name} 빌드 중 …",
    "guided.building.preparing": "준비 중 …",
    "guided.building.note": "1~2분 정도 걸릴 수 있습니다. 무거운 작업은 uv가 처리합니다.",
    "guided.hint.building": "빌드 중 …",
    "guided.done.ready": "{name} 준비 완료",
    "guided.done.body": "프로젝트를 생성하고 의존성을 설치했습니다.",
    "guided.done.next_steps": "다음 단계",
    "guided.done.project_structure": "프로젝트 구조",
    "guided.done.recreate": "이 스택은 언제든 다시 생성할 수 있습니다",
    "guided.done.copy_note": "c를 눌러 복사하세요. 완료 후 아래에 전체 명령이 표시됩니다.",
    "guided.done.copied": "클립보드에 복사됨 ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "계속",
    "guided.header.label": "가이드 설정",
    "guided.hint.move": "이동",
    "guided.hint.select": "선택",
    "guided.hint.toggle": "토글",
    "guided.hint.back": "뒤로",
    "guided.hint.begin": "시작",
    "guided.hint.build": "생성",
    "guided.hint.next": "다음",
    "guided.hint.finish": "완료",
    "guided.hint.quit": "종료",
    "guided.hint.services": "서비스로 건너뛰기",
    "guided.hint.copy": "명령 복사",
    "guided.hint.deps": "의존성",
    "guided.hint.files": "파일",
    "guided.review.core": "코어:",
    "guided.review.infrastructure": "인프라:",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "서비스:",
    "guided.review.auto": "자동",
    "guided.review.build": "{name} 생성",
    "guided.review.more": "… 외 {n}개",
    "guided.screen.requires": "필수:",
    "guided.screen.added_automatically": "(자동 추가됨)",
    "guided.screen.pairs": "함께 쓰면 좋은 항목:",
    "guided.screen.docs": "문서:",
    "component.backend.long": "API를 제공하는 FastAPI 애플리케이션으로, 처음부터 비동기로 설계되었습니다. 타입이 지정된 라우트, 자동 OpenAPI 문서, 헬스 체크, 그리고 이 모든 것을 이미 다루는 테스트 스위트를 포함합니다.",
    "component.frontend.long": "시스템 상태와 여기서 선택한 모든 컴포넌트의 상태를 실시간으로 보여주는 Flet 대시보드로, 직접 만든 화면으로 확장할 수 있습니다. 처음부터 끝까지 Python이며 JavaScript 빌드 체인이 필요 없습니다.",
    "component.worker.long": "백그라운드 작업 처리로, 백엔드를 arq(기본값), Dramatiq, TaskIQ 중에서 선택할 수 있습니다. 이메일 전송, 내보내기, 서드파티 API 호출 같은 느린 작업을 분리해 요청을 빠르게 유지합니다. Redis 위에서 실행되며 자동으로 추가됩니다.",
    "component.scheduler.long": "APScheduler를 사용한 백그라운드 작업 스케줄링과 cron 작업. 정리, 리포트, 헬스 체크 같은 주기적인 작업을 일정에 따라 실행합니다. 선택적인 데이터베이스 영속성으로 작업 기록을 보관하고 재시작 후에도 유지됩니다.",
    "component.database.long": "SQLModel ORM, Alembic 마이그레이션, 커넥션 풀링을 갖춘 영속 저장소. SQLite는 개발용 무설정 파일 데이터베이스를 제공하고, PostgreSQL은 프로덕션용 선택지입니다. 대부분의 서비스가 이를 기반으로 합니다.",
    "component.redis.long": "캐시와 메시지 브로커로 사용되는 인메모리 데이터 저장소. 백그라운드 작업 큐와 서비스 간 pub/sub 메시징을 구동하고, 요청 핸들러에 빠른 공유 캐시를 제공합니다.",
    "component.ingress.long": "Traefik를 이용한 리버스 프록시와 트래픽 라우팅: 자동 서비스 검색, 관리 엔드포인트 보호, Let's Encrypt를 통한 선택적 TLS. 배포의 정문입니다.",
    "component.observability.long": "Pydantic Logfire를 이용한 분산 추적, 메트릭, 로그 상관관계. 애플리케이션을 자동 계측하고 활성화한 컴포넌트에 맞게 적응하므로, 프로덕션이 실제로 무엇을 하는지 볼 수 있습니다.",
    "component.storage.long": "An S3 backend for the object store every stack already has: documents, chat attachments, anything addressed by its content hash. Talks to any S3-compatible endpoint; the dev stack ships SeaweedFS in a container. Switching from the filesystem is a byte copy, never a migration.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "JWT 인증, 세션 쿠키, 리프레시 토큰 회전을 갖춘 완전한 사용자 관리. 세 가지 레벨: 기본 이메일/비밀번호, RBAC 역할 및 권한, 멀티테넌트 조직. 회원가입, 로그인, 관리자 대시보드 탭을 포함합니다.",
    "service.ai.long": "완전한 AI 플랫폼: 멀티 프로바이더 채팅, 약 2000개 모델의 LLM 카탈로그, 사용 분석을 포함한 비용 추적, 코드베이스를 이해하는 대화를 위한 선택적 RAG, 선택적 음성(TTS/STT). 프레임워크는 Pydantic AI 또는 LangChain 중에서 선택합니다.",
    "service.comms.long": "업계 프로바이더를 사용한 이메일, SMS, 음성 통화: 이메일은 Resend, SMS와 음성은 Twilio. 둘 다 무료 등급이 있어 신용카드 없이 시작할 수 있습니다.",
    "service.insights.long": "GitHub, PyPI, Plausible Analytics, Reddit 전반에서 프로젝트의 채택 현황을 자동으로 추적합니다. 일정에 따라 수집하고 기록을 저장하며 대시보드에서 성장을 시각화합니다.",
    "service.payment.long": "Stripe를 이용한 결제 처리: 체크아웃 세션, 구독, 웹훅, 환불. Stripe의 테스트 모드는 신용카드가 필요 없어 출시 전에 전체 흐름을 만들 수 있습니다.",
    "service.documents.long": "Durable storage for the paper an application accumulates: scans, statements, letters, forms. Bytes are addressed by their own content hash, so the same file uploaded twice is one document and one object, and moving to a bucket later is a copy rather than a migration.",
    "service.blog.long": "데이터베이스 기반 게시물, 태그, 초안, 대시보드 내 편집기 UI를 갖춘 자체 Markdown 퍼블리싱. 게시물을 frontmatter가 포함된 일반 Markdown으로 가져오고 내보낼 수 있습니다.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "인메모리",
    "guided.choice.scheduler.memory": "영속성 없음. 재시작 시 작업이 초기화됩니다. 잘 모르겠다면 건너뛰세요.",
    "guided.choice.scheduler.sqlite": "작업 기록을 파일 데이터베이스에 보관합니다.",
    "guided.choice.scheduler.postgres": "작업 기록을 보관, 프로덕션급.",
    "guided.choice.worker.arq": "간단하고 충분히 검증된 비동기 워커로, 설정이 최소한입니다. I/O 바운드 작업에 가장 적합합니다. 기본값.",
    "guided.choice.worker.dramatiq": "멀티프로세스 액터 모델. 여러 OS 프로세스의 이점을 살리는 CPU 바운드 작업에 가장 적합합니다.",
    "guided.choice.worker.taskiq": "비동기 네이티브. 큐별 브로커와 확인 응답을 지원하는 Redis Streams 전송을 사용합니다.",
    "guided.choice.db.sqlite": "무설정 파일 데이터베이스. 개발에 적합합니다.",
    "guided.choice.db.postgres": "프로덕션급, 커넥션 풀링.",
    "guided.choice.db_provider.container": "로컬 postgres:16 컨테이너, 개발 및 운영.",
    "guided.choice.db_provider.neon": (
        "서버리스 Postgres: 운영은 클라우드, 개발은 로컬 컨테이너."
    ),
    "guided.choice.auth.basic": "이메일과 비밀번호, JWT 세션 포함.",
    "guided.choice.auth.rbac": "역할과 권한을 추가합니다.",
    "guided.choice.auth.org": "멀티테넌트 조직.",
    "guided.choice.framework.pydantic_ai": "타입이 지정되고 가볍습니다. 기본값.",
    "guided.choice.framework.langchain": "방대한 생태계, 다양한 통합.",
    "guided.choice.storage.memory": "기록 없음, 설정할 것 없음.",
    "guided.choice.storage.sqlite": "채팅 기록을 파일 데이터베이스에 보관합니다.",
    "guided.choice.storage.postgres": "영속적이고 프로덕션급.",
    "guided.choice.provider.public.desc": "무료 공개 엔드포인트",
    "guided.choice.provider.public.pricing": "무료, API 키 불필요",
    "guided.choice.provider.openai.desc": "GPT 모델",
    "guided.choice.provider.openai.pricing": "유료",
    "guided.choice.provider.anthropic.desc": "Claude 모델",
    "guided.choice.provider.anthropic.pricing": "유료",
    "guided.choice.provider.google.desc": "Gemini 모델",
    "guided.choice.provider.google.pricing": "무료 등급(Flash만)",
    "guided.choice.provider.groq.desc": "빠른 추론",
    "guided.choice.provider.groq.pricing": "무료 등급",
    "guided.choice.provider.mistral.desc": "오픈 모델",
    "guided.choice.provider.mistral.pricing": "대부분 유료",
    "guided.choice.provider.cohere.desc": "엔터프라이즈 중심",
    "guided.choice.provider.cohere.pricing": "제한적 무료",
    "guided.choice.provider.ollama.desc": "로컬 추론",
    "guided.choice.provider.ollama.pricing": "무료(로컬)",
    "build.step.render": "프로젝트 파일 생성 중",
    "build.step.deps": "의존성 설치 중",
    "build.step.env": "환경 설정",
    "build.step.migrate": "마이그레이션 적용 중",
    "build.step.llm": "LLM 카탈로그 동기화 중",
    "build.step.format": "코드 포매팅 중",
}
