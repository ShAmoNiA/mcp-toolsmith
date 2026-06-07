# Release

Maintainer notes for publishing `mcp-toolsmith`.

## Checklist

Use a clean working tree:

```bash
git status --short
```

Remove local build outputs:

```bash
rm -rf dist build *.egg-info
```

Run checks:

```bash
pytest
ruff check .
python -m build
twine check dist/*
```

Publish to TestPyPI first:

```bash
twine upload --repository testpypi dist/*
```

Then test installation in a clean virtual environment:

```bash
python -m venv .test-venv
.test-venv\Scripts\activate
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple mcp-toolsmith==0.2.0
mcp-toolsmith --help
```

If TestPyPI works, publish the same artifacts to PyPI:

```bash
twine upload dist/*
```

Do not commit `dist/`, `build/`, caches, virtual environments, or source
archives containing `.git/`.
