# Security Policy

## Supported versions

Security fixes are applied to the latest released minor version. Older versions
do not receive backported patches.

| Version | Supported |
| ------- | --------- |
| latest  | ✅        |
| older   | ❌        |

## Reporting a vulnerability

Please report security vulnerabilities privately, **not** through a public issue.

Use GitHub's private vulnerability reporting:
https://github.com/empirico-oss/gc-batch/security/advisories/new

Please include:

- a description of the issue and its impact
- the affected version(s)
- steps to reproduce, or a proof of concept
- any suggested mitigation

We aim to acknowledge reports within 5 business days and to provide a remediation
plan or timeline within 30 days.

Please do not include credentials, access tokens, cloud project identifiers, or
any participant or patient data in your report.

## Scope

`gc-batch` is a client that submits jobs to the Google Cloud Batch API using the
caller's own credentials. In scope: vulnerabilities in this package, such as
credential or token leakage through logs or error messages, command or argument
injection through CLI inputs, insecure handling of the settings file, or
unintended privilege escalation in job configuration.

Out of scope: vulnerabilities in Google Cloud itself, in the `google-cloud-*`
client libraries, or misconfiguration of a user's own cloud project or IAM
policies. Please report those to the relevant vendor.
