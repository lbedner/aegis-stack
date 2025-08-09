# 🛡️ Aegis Stack CLI Testing Guide

This guide explains how to test the Aegis Stack CLI to ensure it generates correct projects and handles all scenarios properly.

## Test Structure

```
tests/
├── cli/                          # CLI integration tests
│   ├── test_cli_basic.py        # Fast tests (command parsing, help, validation)
│   ├── test_cli_init.py         # Slow tests (full project generation)
│   └── conftest.py              # CLI test configuration
├── conftest.py                  # Main test configuration
└── test_health.py               # Existing health tests
```

## Test Categories

### 🏃‍♂️ Fast Tests (`test_cli_basic.py`)
- **Command parsing**: CLI accepts valid arguments  
- **Help text**: All commands show proper help
- **Validation**: Invalid components are rejected
- **Error handling**: Missing arguments show helpful errors

**Run with**: `uv run pytest tests/cli/test_cli_basic.py -v`

### 🐌 Slow Tests (`test_cli_init.py`) 
- **Project generation**: Full project creation with components
- **Template processing**: `.j2` files rendered correctly
- **File structure**: Generated projects have expected files
- **Quality checks**: Generated code passes linting/type checking

**Run with**: `uv run pytest tests/cli/test_cli_init.py --runslow -v`

## Running Tests

### Quick Test (2-3 seconds)
```bash
# Run just the fast CLI tests
uv run pytest tests/cli/test_cli_basic.py -v
```

### Single Integration Test (5-10 seconds)
```bash
# Test scheduler component generation
uv run pytest tests/cli/test_cli_init.py::TestCLIInit::test_init_with_scheduler_component --runslow -v
```

### All Fast Tests (5-10 seconds)
```bash
# Run all tests except slow ones
uv run pytest tests/ -v -m "not slow"
```

### All Tests Including Slow (30-60 seconds)
```bash
# Run everything including project generation
uv run pytest tests/ --runslow -v
```

### Using the Test Script
```bash
# Run the comprehensive test script
./test_cli.sh
```

## What Each Test Validates

### CLI Command Structure
- ✅ `aegis --help` shows main commands
- ✅ `aegis init --help` shows all options  
- ✅ `aegis version` returns version info
- ✅ `aegis status` works in project directories

### Component Validation
- ✅ Valid components (`scheduler`, `database`, `cache`) are accepted
- ✅ Invalid components show clear error messages
- ✅ Multiple components can be specified
- ✅ Component names are case-sensitive

### Project Generation Output
```
🛡️  Aegis Stack Project Initialization
==================================================
📁 Project will be created in: /path/to/project

📁 Project Name: test-project
🏗️  Project Structure:
   ✅ Core (backend: FastAPI, frontend: Flet)
   ✅ Additional Components:
      • scheduler

📄 Files to be generated:
   • app/components/scheduler.py
   • tests/components/test_scheduler.py

📦 Dependencies to be installed:
   • apscheduler

🔧 Creating project: test-project
Processed template: pyproject.toml.j2 -> pyproject.toml
Processed template: README.md.j2 -> README.md
Processed template: scheduler.py.j2 -> scheduler.py
✅ Project created successfully!
```

### Generated Project Structure
```
project/
├── app/
│   ├── components/
│   │   └── scheduler.py          # ✅ Only when scheduler selected
│   ├── services/                 # ✅ Empty directory
│   └── [core files...]
├── tests/
│   └── components/
│       └── test_scheduler.py     # ✅ Only when scheduler selected
├── pyproject.toml                # ✅ Rendered from template
└── [other core files...]
```

### Template Processing
- ✅ No `.j2` files remain in generated projects
- ✅ `{{ cookiecutter.project_name }}` replaced correctly
- ✅ Component-specific dependencies added to `pyproject.toml`
- ✅ APScheduler mypy overrides added when scheduler selected

### Code Quality
- ✅ Generated projects install dependencies successfully
- ✅ Linting passes (with auto-fixes applied)
- ✅ Type checking passes with mypy strict mode
- ✅ Tests run without critical failures

## Test Scenarios Covered

### ✅ Successful Generation
1. **With scheduler**: `--components scheduler`
2. **No components**: Core project only
3. **Custom project name**: Proper variable substitution
4. **Multiple components**: When database/cache implemented

### ✅ Error Handling
1. **Invalid components**: Clear error messages
2. **Missing project name**: Usage information
3. **Conflicting options**: Proper validation

### ✅ Edge Cases
1. **Force overwrite**: `--force` flag works
2. **Custom output directory**: `--output-dir` respected
3. **Non-interactive mode**: `--no-interactive` skips prompts

## Adding New Tests

### For New Components (database, cache)
1. Add component validation to `test_cli_basic.py`
2. Add integration test to `test_cli_init.py`
3. Update CLI output expectations
4. Add file structure assertions

### For New CLI Commands
1. Add basic command tests to `test_cli_basic.py`
2. Add help text validation
3. Create integration tests if needed

### Example Test Structure
```python
def test_new_component_generation(self, temp_output_dir, skip_slow_tests):
    """Test generating project with new component."""
    result = run_aegis_init(
        project_name="test-new-component",
        components=["new_component"],
        output_dir=temp_output_dir
    )
    
    # Assert CLI output
    assert result.success
    assert "• new_component" in result.stdout
    assert "• app/components/new_component.py" in result.stdout
    
    # Assert project structure
    assert_file_exists(result.project_path, "app/components/new_component.py")
    
    # Assert template processing
    self._assert_new_component_template_processing(result.project_path)
```

## Debugging Test Failures

### CLI Command Failures
- Check `result.stderr` for error messages
- Verify command arguments match expected format
- Ensure running from correct directory

### Project Generation Failures
- Check temp directory permissions
- Verify template files exist in source
- Look for cookiecutter or Jinja2 errors

### File Structure Assertions
- Use `assert_file_exists()` helper function
- Check file permissions and content
- Verify template substitution worked

## Performance Considerations

- **Fast tests** should complete in under 10 seconds
- **Slow tests** can take 30-60 seconds for full project generation
- Use `--runslow` flag to control which tests run
- Consider parallel test execution for CI/CD

## CI/CD Integration

```yaml
# Example GitHub Actions workflow
- name: Run Fast CLI Tests
  run: uv run pytest tests/cli/test_cli_basic.py -v

- name: Run CLI Integration Tests  
  run: uv run pytest tests/cli/test_cli_init.py --runslow -v
```