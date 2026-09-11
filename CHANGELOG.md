# Changelog

All notable changes to `mimiqlink` (Python) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] — 2026-09-11

### Added

- `QhiveConnection` connects to Quantum Hive web services, authenticating
  through Keycloak with a browser login, a username and password, or an
  existing token.

### Build

- Dependencies are locked with `uv.lock`. The tracked `poetry.lock` is gone: it
  predated the `python-keycloak` dependency and no longer described the
  package.
- Test dependencies live in the PEP 735 `test` dependency group, so
  `uv sync --group test` installs them. They now require pytest 9 and
  responses 0.26.
- Dependency bounds close at the next version each dependency is allowed to
  break in: requests `>=2.34,<3`, python-keycloak `>=4.7,<5`, tabulate
  `>=0.10,<0.11`.
- The package and its dependencies import on the free-threaded CPython 3.14
  build without re-enabling the GIL.

### Fixed

- The `Repository` project URL points at `mimiqlink-python` rather than
  `mimiqcircuits-python`.

## [0.8.4]

Changelog tracking begins with this version. See git history for prior changes.
