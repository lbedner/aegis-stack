# Aegis Stack - AI Development Context

## 🛡️ Mission & Philosophy

**Aegis Stack exists for builders who refuse to wait.** It's a production-ready Python foundation — minimal, async-first, battle-tested — designed for developers who think in systems, not scripts.

### Core Principles
- **AI as a Catalyst, Not Competition**: Designed for human-AI collaboration with LLM-friendly structure
- **Single Language Mastery**: Python everywhere - FastAPI backend to Flet frontend
- **Async-First Architecture**: Built with `async` as primary concern for performance
- **Minimalist by Default**: Strong, clean foundation without unnecessary bloat
- **Build what doesn't exist. Launch before anyone else.**

## 🏗️ Architecture Overview

### Tech Stack
- **Frontend**: Flet (Python-native UI)
- **Backend**: FastAPI (async APIs)
- **Data**: Pydantic (type safety across stack)
- **Tasks**: Dramatiq (async background processing)
- **Scheduling**: APScheduler (periodic jobs)
- **Observability**: Pydantic Logfire + structlog
- **Infrastructure**: Docker, Terraform (AWS), LocalStack

### Project Structure
```
app/
├── frontend/           # Flet client application
│   ├── views/         # UI views and pages
│   ├── components/    # Reusable UI components
│   └── routing/       # Navigation logic
├── backend/           # FastAPI server
│   ├── api/          # API endpoints
│   ├── auth/         # JWT authentication
│   ├── models/       # Pydantic models
│   └── services/     # Business logic
docs/                  # Documentation
tests/                 # Test suite
```

## 🤖 AI-Native Features

### Manifest-Driven Development
The `aegis_manifest.json` serves as a machine-readable blueprint enabling AI agents to understand project structure, dependencies, and conventions for safe, accurate code generation.

### Structured for AI
- Predictable module organization
- Consistent naming conventions
- Pydantic models for type safety
- Clear separation of concerns

## 🚀 Development Guidelines

### Code Style
- Follow existing patterns and conventions
- Use async/await consistently
- Leverage Pydantic for data validation
- Implement proper error handling
- No comments unless explicitly needed

### Security
- Never expose or log secrets/keys
- Use JWT for authentication
- Validate all inputs with Pydantic
- Follow principle of least privilege

### Testing
- Write tests for all new features
- Use pytest with async support
- Maintain high test coverage
- Test error conditions

## 📊 Observability

### Logging Strategy
- **Development**: Colored console logs with structlog
- **Production**: Structured JSON for ingestion (Datadog, CloudWatch)
- **Monitoring**: Real-time dashboards via Pydantic Logfire

### Key Metrics
- Request/response times
- Error rates and exceptions
- Background job status
- System health indicators

## 🛠️ CLI Integration

The project includes a Typer-based CLI for:
- Project initialization
- Code generation
- Development workflows
- Deployment tasks

## 💡 Prompt Engineering Tips

When working with Aegis Stack:
1. Always check existing patterns before adding new code
2. Use Pydantic models for data structures
3. Follow the async-first principle
4. Implement proper error handling
5. Consider observability from the start

---

*This file is automatically updated to reflect the current project state and conventions.*