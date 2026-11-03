# GitHub automation

This folder contains scheduled/manual automation for the OCI instance-creation prototype. Read workflows/README.md before changing or invoking it. The current workflow has a 10-minute cron and can call an OCI API that creates billable resources. It must not be treated as a harmless CI check. Never expose GitHub Secrets or raw runner output. Project cost ceiling is €0; do not run until Always Free eligibility and all dependent resource costs are proven.
