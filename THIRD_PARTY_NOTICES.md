# License and third-party notices

## Project code and documentation

The project is licensed under the [MIT License](LICENSE), copyright
(c) 2026 yoonpyohong. Keep the copyright and permission notice in copies or
substantial portions. This update preserves that license and attribution; it does
not relicense third-party works. Installed package metadata declares SPDX `MIT`
and includes the license file.

## University names, content and screenshots

Yonsei University, LearnUs and related names/logos identify the services with which
this independent project interoperates. They do not imply endorsement, sponsorship
or official support. No trademark rights are granted by this repository's license.

University pages, notices, course materials and service UI shown in documentation
remain subject to their owners' rights and applicable terms. The MIT license does
not grant permission to republish those materials or personal student data. Example
screenshots are documentation, not permission to redistribute underlying course
content. Do not submit screenshots or transcripts containing private information.

## Dependencies

Third-party Python packages and Chromium/Playwright components retain their own
licenses. Consult each installed distribution's license metadata and upstream
project before redistribution. The MIT license for this project does not replace
those licenses. The lockfile records dependency versions; dependencies are not
vendored into the project's wheel.

## Bundled public certificate

`src/yonsei_portal_mcp/_certs/sectigo_ov_intermediate.pem` is a public Sectigo
intermediate CA certificate, not a private key or credential. It supplements the
verified TLS trust chain for an upstream missing intermediate; TLS checks remain
active. It does not contain project code and must not be treated as a grant of
Sectigo trademark rights or as an endorsement. Certificate validity and upstream
chain changes must be reviewed when updating it.
