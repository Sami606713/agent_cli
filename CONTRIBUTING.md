# Contributing to langctl

Thank you for your interest in contributing to langctl! This guide will help you get started.

## Development Setup

1. **Fork and clone**
   ```bash
   git clone https://github.com/<your-username>/agent_cli.git
   cd agent_cli
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # .venv\Scripts\activate   # Windows
   ```

3. **Install in development mode**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run tests**
   ```bash
   pytest
   ```

## Branch Workflow

- **Never push directly to `main`** — it's protected.
- Create a feature branch from `main`:
  ```bash
  git checkout -b feature/your-feature-name
  ```
- Push your branch and open a Pull Request.
- All PRs require at least 1 approval before merging.
- All review conversations must be resolved before merging.

## Branch Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feature/description` | `feature/deploy-vercel` |
| Bug fix | `fix/description` | `fix/proxy-timeout` |
| Docs | `docs/description` | `docs/contributing-guide` |
| Refactor | `refactor/description` | `refactor/config-loader` |

## Pull Request Process

1. **Keep PRs focused** — one feature or fix per PR.
2. **Write a clear description** — what changed and why.
3. **Update tests** — if you change behavior, update or add tests.
4. **Update docs** — if you add a command or change config, update README.
5. **Run tests locally** before pushing:
   ```bash
   pytest
   ruff check src/
   ruff format --check src/
   ```

## Code Style

- We use **Ruff** for linting and formatting.
- Python 3.11+ features are welcome.
- Type hints are encouraged.
- Keep functions focused — one function, one job.

## What to Contribute

Check the [Issues](https://github.com/Sami606713/agent_cli/issues) tab for tasks labeled:
- `good first issue` — great for first-time contributors
- `enhancement` — new features
- `bug` — confirmed bugs
- `documentation` — docs improvements

## Reporting Bugs

Open an issue with:
- What you did (commands run)
- What you expected
- What actually happened
- Your OS, Python version, and langctl version (`langctl --version`)

## Code of Conduct

Be respectful, constructive, and welcoming. We're building something useful together.

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 License.
