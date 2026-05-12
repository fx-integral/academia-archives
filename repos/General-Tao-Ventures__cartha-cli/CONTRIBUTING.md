# Contributing to Cartha CLI

Thank you for your interest in contributing to the Cartha CLI! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) package manager or `pip`
- Git
- Basic understanding of Bittensor and EIP-712 signatures

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/General-Tao-Ventures/cartha-cli.git
   cd cartha-cli
   ```

2. **Install dependencies for development**

   ```bash
   # Using uv (recommended for development)
   uv sync
   
   # Or using pip in editable mode
   pip install -e ".[dev]"
   ```

3. **Run tests**

   ```bash
   pytest
   # or
   make test
   ```

## Development Workflow

### 1. Find Something to Work On

- Check [open issues](https://github.com/your-org/cartha-cli/issues)
- Look for `good first issue` labels
- Discuss major changes before starting (open an issue first)

### 2. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 3. Make Your Changes

- Write clean, readable code
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed

### 4. Test Your Changes

```bash
# Run tests
pytest

# Test CLI commands locally
cartha --help
cartha miner status --help
```

### 5. Commit Your Changes

- Write clear, descriptive commit messages
- Keep commits focused and atomic
- Reference issue numbers when applicable

Example:

```bash
git commit -m "feat: add --dry-run flag to prove-lock command

- Allow users to test lock proof without submitting
- Add validation for dry-run mode
- Fixes #123"
```

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a pull request on GitHub.

## Code Style

### Python Style

- Follow PEP 8
- Use type hints
- Run linters before committing
- Use `typer` for CLI commands

### Code Organization

- Keep commands focused and small
- Add docstrings for public functions
- Use meaningful variable names
- Comment complex logic

### Testing

- Write tests for new commands
- Test both success and failure cases
- Use fixtures for common test data
- Test with both testnet and mainnet configs

## Pull Request Guidelines

### Before Submitting

- [ ] Code follows the project's style guidelines
- [ ] Tests pass locally
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] PR description explains the changes
- [ ] CLI commands work as expected

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Refactoring

## Testing
How was this tested?

## CLI Changes
- [ ] New command added
- [ ] Existing command modified
- [ ] Breaking change (document migration path)

## Related Issues
Closes #123
```

### Review Process

- Maintainers will review your PR
- Address feedback promptly
- Be open to suggestions
- Keep discussions constructive

## Project Structure

```text
cartha-cli/
├── cartha_cli/          # Main CLI code
│   ├── main.py         # CLI entry point (Typer app)
│   ├── bt.py           # Bittensor helpers
│   ├── eth712.py       # EIP-712 signature helpers
│   ├── verifier.py     # Verifier API client
│   └── config.py       # Configuration
├── testnet/            # Testnet-specific helpers
│   └── pool_ids.py     # Pool ID conversion helpers
├── tests/              # Test suite
└── pyproject.toml      # Project config
```

## Areas for Contribution

### Code Contributions

- Bug fixes
- New CLI commands
- Performance improvements
- Code refactoring
- Test coverage improvements

### Documentation

- Improve existing docs
- Add command examples
- Fix typos
- Add tutorials
- Improve error messages

### Test

- Add test cases
- Improve test coverage
- Add integration tests
- Test edge cases

## CLI-Specific Guidelines

### Command Design

- Use clear, intuitive command names
- Provide helpful error messages
- Include examples in help text
- Support both testnet and mainnet

### User Experience

- Make commands easy to use
- Provide sensible defaults
- Validate inputs early
- Give clear feedback

### Security

- Never log private keys or mnemonics
- Never commit secrets
- Validate all inputs
- Use secure defaults

### Error Handling

- Provide helpful error messages
- Suggest solutions when possible
- Log errors appropriately
- Handle edge cases gracefully

## Adding New Commands

When adding a new command:

1. Add the command function to `cartha_cli/main.py`
2. Use `@app.command()` decorator
3. Add type hints
4. Add docstring
5. Add tests
6. Update documentation

Example:

```python
@app.command()
def new_command(
    arg: str = typer.Option(..., help="Description"),
) -> None:
    """Brief description of the command."""
    # Implementation
    pass
```

## Questions?

- Check the [README](README.md) for general information
- Review the [testnet guide](testnet/README.md) for testnet-specific info
- Open an issue for questions
- Ask in discussions

## Code of Conduct

All contributors are expected to:

- Be respectful and inclusive
- Provide constructive feedback
- Help others learn
- Follow project guidelines

## Recognition

Contributors are recognized in:

- Release notes
- Project documentation
- GitHub contributors list

Thank you for contributing to Cartha CLI! 🎉
