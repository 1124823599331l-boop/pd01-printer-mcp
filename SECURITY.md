# Security Policy

This project controls physical hardware and can consume paper.

## Safe deployment requirements

- Keep the default `127.0.0.1` bind address for local use.
- Require HTTPS and authentication before remote exposure.
- Apply request-size and rate limits at the network edge.
- Never commit real device addresses, server addresses, credentials, keys, logs, or print content.
- Treat `CONFIRM_PRINT` as a workflow guard, not as authentication.

## Reporting a vulnerability

Open a GitHub security advisory or contact the repository maintainer privately. Do not include credentials, private print content, or identifying device data in a public issue.
