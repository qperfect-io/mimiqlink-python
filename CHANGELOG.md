# Changelog

All notable changes to `mimiqlink` (Python) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.1] — 2026-09-27

### Added

- `MimiqConnectionError` is the single exception the library raises, and is
  exported from `mimiqlink`. It derives from the builtin `ConnectionError`, and
  the old `mimiqlink.abstractconnection.ConnectionError` name still resolves to
  it, so both ways of catching a failure keep working.

### Fixed

- The library no longer raises two unrelated exception classes that happen to
  share a name. `abstractconnection` defined its own `ConnectionError`, which
  shadowed the builtin inside that module only: seven raise sites used it and
  the other thirty-three, in the connection types, raised the builtin. Catching
  one missed the other.

- `MimiqConnection.close()` no longer hangs. It held the refresher lock while
  joining the refresher thread, and the thread needs that same lock once a
  second to notice it was asked to stop, so a closed connection never came
  back. Reconnecting an already-open connection deadlocked the same way.

### Tooling

- The test suite drives the client against in-process stand-ins for the MIMIQ
  and Quantum Hive APIs, covering authentication, token rotation, the job
  lifecycle, downloads and the failure paths without reaching the network.
- GitLab CI runs the suite on every supported interpreter, 3.10 through 3.14
  and free-threaded 3.14, and builds the package.

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
