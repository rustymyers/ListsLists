# Validation record

Static validation completed for this generated v1 project:

- All Python files compile and parse as valid Python 3 syntax.
- All 16 Jinja templates parse successfully.
- `pyproject.toml` and `compose.yaml` parse successfully.
- All shell scripts pass `sh -n` syntax validation.
- The project exposes 56 server/API route declarations.

The included pytest suite covers local authentication, authorization, strict nested-list permissions, cycle rejection, quantity/duplicate resolution, JSON/CSV exports, and item reorder/copy/move/delete operations.

The full pytest suite was not executed in the generation sandbox because its package index did not provide SQLAlchemy, Alembic, or pwdlib. Run `pip install -e '.[dev]' && pytest` in a normal Python 3.12 environment or build the supplied container before production use.
