# Release validation — 0.1.0

Prepared on 2026-09-22; final packaging checks on 2026-09-23.

- The copied portal/backend's 31 unit tests passed in an isolated container with networking disabled, read-only source mounts and temporary test data.
- The validation container reused installed dependencies from the existing runtime through a read-only volume mount. It did not start model inference or modify existing services/data.
- Docker Compose configuration validation passed with the example model settings.
- PowerShell scripts parsed successfully; the preparation script created the three expected local configurations and preserved existing settings on a second run.
- Bash startup/preparation syntax and portal JavaScript syntax checks passed.
- The integration Dockerfile was copied byte-for-byte from the existing workspace.
- The source package was checked for local environment files, credentials, model weights, runtime databases and personal filesystem paths. An upstream unit-test fixture deliberately contains a fake API key; no real credentials were included.
- Third-party licenses include Danus, browser libraries and the SIL OFL 1.1 font notices extracted from the bundled fonts.

This was a source-package validation, not a fresh deployment on every supported operating system. A clean image build and first-run dependency downloads were not executed as part of packaging, to preserve the existing installation. Search-provider availability and a new user's model/tool-calling compatibility must be checked on that user's machine.
