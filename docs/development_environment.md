# Development Environment

Install the project in editable mode:

```bash
python -m pip install -e .
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

The test suite uses only the standard-library runner, matching GitHub Actions.
