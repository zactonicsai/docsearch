# DocMS Worker Test Suite — Usage Examples

## Quick Start

### Linux / macOS

```bash
# 1. Place test files alongside your source files
cp conftest.py test_*.py pyproject.toml run_tests.sh /path/to/your/project/

# 2. Make the script executable and run
cd /path/to/your/project
chmod +x run_tests.sh
./run_tests.sh
```

### Windows

```cmd
REM 1. Place test files alongside your source files
copy conftest.py test_*.py pyproject.toml run_tests.bat C:\path\to\your\project\

REM 2. Run from command prompt
cd C:\path\to\your\project
run_tests.bat
```

---

## Running Specific Tests

### Run a single test file

```bash
python -m pytest test_worker.py -v
```

### Run a single test class

```bash
python -m pytest test_worker.py::TestExtractCsv -v
```

### Run a single test method

```bash
python -m pytest test_worker.py::TestExtractPdf::test_with_pymupdf -v
```

### Run tests matching a keyword

```bash
python -m pytest -k "ocr" -v              # all OCR-related tests
python -m pytest -k "elasticsearch" -v     # all ES-related tests
python -m pytest -k "workflow" -v          # all workflow tests
```

---

## Coverage Options

### Terminal report with missing lines

```bash
python -m pytest --cov=worker --cov-report=term-missing
```

### Generate HTML coverage report

```bash
python -m pytest --cov=worker --cov-report=html:htmlcov
# Then open htmlcov/index.html in your browser
```

### Generate XML report (for CI)

```bash
python -m pytest --cov=worker --cov-report=xml:coverage.xml
```

### Enforce minimum coverage threshold

```bash
python -m pytest --cov=worker --cov-fail-under=90
```

### Branch coverage (default in pyproject.toml)

```bash
python -m pytest --cov=worker --cov-branch
```

---

## Passing Extra Arguments via the Shell Script

Both `run_tests.sh` and `run_tests.bat` forward extra arguments to pytest:

```bash
# Run only tests matching "pdf", with verbose output
./run_tests.sh -k "pdf" -v

# Stop on first failure
./run_tests.sh -x

# Show local variables in tracebacks
./run_tests.sh --tb=long -l

# Run in parallel (requires pytest-xdist)
pip install pytest-xdist
./run_tests.sh -n auto
```

---

## Environment Variables

Override these before running tests to match your infrastructure:

```bash
# Linux / macOS
export ELASTICSEARCH_URL="http://my-es-host:9200"
export BACKEND_URL="http://my-backend:8080"
export TEMPORAL_HOST="my-temporal:7233"
./run_tests.sh
```

```cmd
REM Windows
set ELASTICSEARCH_URL=http://my-es-host:9200
set BACKEND_URL=http://my-backend:8080
set TEMPORAL_HOST=my-temporal:7233
run_tests.bat
```

> **Note:** The test suite mocks all external services (Temporal, Elasticsearch, backend HTTP).
> No running infrastructure is needed — these variables only affect module-level defaults.

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install pytest pytest-asyncio pytest-cov pytest-mock httpx elasticsearch temporalio

      - name: Run tests
        run: bash run_tests.sh

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: htmlcov/
```

### GitLab CI

```yaml
test:
  image: python:3.12
  script:
    - pip install pytest pytest-asyncio pytest-cov pytest-mock httpx elasticsearch temporalio
    - bash run_tests.sh
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - htmlcov/
```

---

## Project Structure

```
your-project/
├── shared.py                # Dataclasses (DocumentTask, ExtractionResult, IndexResult)
├── activities.py            # Temporal activities (extract, index, update status)
├── workflows.py             # Temporal workflow definition
├── worker.py                # Monolithic worker (extractors + activities + workflow + entry point)
├── run_worker.py            # Standalone worker entry point
├── conftest.py              # Shared pytest fixtures
├── pyproject.toml           # Pytest + coverage configuration
├── run_tests.sh             # Linux/macOS test runner
├── run_tests.bat            # Windows test runner
├── test_shared.py           # 11 tests — dataclass validation
├── test_activities.py       # 17 tests — activities + unstructured extractor
├── test_workflows.py        #  4 tests — workflow orchestration logic
├── test_worker.py           # 50 tests — all extractors, routing, activities, workflow, startup
└── test_run_worker.py       #  4 tests — entry point startup/retry logic
                             # ── 86 tests total, 96.46% branch coverage ──
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: temporalio` | `pip install temporalio` |
| `ModuleNotFoundError: pytest_asyncio` | `pip install pytest-asyncio` |
| Tests pass but coverage is below 90% | Check `Missing` column in the report — add tests for uncovered lines |
| `permission denied: run_tests.sh` | `chmod +x run_tests.sh` |
| Windows: `'python' is not recognized` | Add Python to your system PATH |
| Coverage report not generated | Ensure `pytest-cov` is installed: `pip install pytest-cov` |
