# OCI Sniper workflow — high-risk automation

- sniper.yml schedules a run every 10 minutes and also supports manual dispatch.
- It installs OCI SDK dependencies and runs sniper.py with GitHub Secrets.
- sniper.py calls OCI Compute LaunchInstance. This is a resource-creation workflow, not a read-only capacity check.
- The script tries 4 OCPU/24 GB and 2 OCPU/12 GB ARM shapes and configures a 200 GB boot volume. Do not assume all combinations, IPs, storage, or traffic are Always Free.
- The workflow has no demonstrated €0 cost guard and no independent post-create billing validation.

**Do not dispatch or enable this workflow** under the MC SERVER zero-cost policy until every resource is verified as Always Free for the actual tenancy/region and the total maximum cost is documented as €0. Do not print or inspect secret values. Review the current workflow YAML and script before any future change.
