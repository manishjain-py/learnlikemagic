# Terraform State Reconciliation — Handover

**Status:** ✅ complete (2026-05-01) · **Outcome:** zero-diff achieved, no production downtime · **Effort:** ~1.5 hours actual.

## Result (2026-05-01)

- State went from **11 → 45 resources** tracked. Every prod resource is now imported.
- Final `terraform plan` reports `No changes. Your infrastructure matches the configuration.`
- A single targeted `terraform apply` flushed 12 benign in-place updates (state-only quirks, tag adds/removes, sensitive-flag flips, secret-version re-writes with identical values, cognito-policy data-source resolution).
- **No App Runner deployment was triggered** — AWS treated the apprunner service update as metadata-only. The most recent op remained the 19:03 EL cutover. Backend/frontend smoke checks: HTTP 200 / 301. Zero downtime.
- State backups created at every step: `terraform.tfstate.pre-{ecr,secrets,oidc,apprunner,frontend,final-apply}-<timestamp>` in `infra/terraform/`. Safe to delete after a quiet-week soak.

### Code changes committed alongside the imports

- Stripped redundant `Environment = var.environment` from every resource-level `tags` block (it's already in `default_tags` on the root provider, so duplicates caused churn after import).
- App Runner module: added Cognito vars (`cognito_app_client_id`, `cognito_region`, `cognito_user_pool_id`) and wired them into `runtime_environment_variables` + a new `cognito-admin` inline policy.
- App Runner module: `GOOGLE_CLOUD_TTS_API_KEY` moved from secret-ref → plain-text env var (matches manual prod state; **hygiene deferred**).
- App Runner module: `DATABASE_URL` left as plain-text env var with embedded password (matches manual prod state; **hygiene deferred**).
- App Runner module: `secrets-access` inline policy split into 4 — `secrets-access` (openai-only), `anthropic-secret-access`, `elevenlabs-secret-access`, `cognito-admin` — to match live shape.
- App Runner module: dropped `GEMINI_API_KEY` from `runtime_environment_secrets` (not actually wired in prod). The gemini secret is still tracked but unreferenced.
- App Runner module: health-check path `/health` → `/` (matches live).
- Root `variables.tf`: added Cognito var defaults from live values.
- Root `main.tf`: wired new app-runner inputs (`cognito_*`, `google_cloud_tts_api_key = var.gemini_api_key`).
- `terraform.tfvars`: added `elevenlabs_api_key` (was missing; needed for module.secrets count).

### Decisions kept open from this work

1. Move `GOOGLE_CLOUD_TTS_API_KEY` from plain-text env back to a Secrets Manager reference.
2. Move DB password out of `DATABASE_URL` and assemble at app start from a Secrets Manager reference.
3. Migrate Terraform state from local-only to an S3 backend + DynamoDB locking.

These remain in the "deferred-but-related cleanups" list at the bottom of this doc.

---

**Original handover starts below; preserved for historical reference.**

---



## Problem

`infra/terraform/` state is severely drifted from production. Local state file (last touched 2026-04-03) tracks **11 resources**; production has **~30+**. Running `terraform apply` would attempt to **create 28 new resources**, most of which would fail with `ResourceAlreadyExistsException` (App Runner service, IAM roles, ECR repo, secrets, S3 bucket — all globally/region-unique names already taken by live prod resources). CloudFront would create a duplicate distribution serving the same content, since CloudFront IDs are auto-generated.

State is local-only — no S3 backend block in `main.tf`. State files are gitignored.

The drift exists because production was extended manually after the initial Terraform applies, and state was never reconciled. Manual ops layered on:
- Cognito User Pool integration (env vars, IAM `cognito-admin` inline policy)
- Anthropic API key secret + a separate `anthropic-secret-access` inline policy (code expects it bundled into `secrets-access`)
- ElevenLabs API key secret + `elevenlabs-secret-access` inline policy + `TTS_PROVIDER` env (added 2026-05-01 during the EL cutover, see PR #138)
- Plain-text `GOOGLE_CLOUD_TTS_API_KEY` env var (code says it should be a secret reference)
- DATABASE_URL with embedded plain-text DB password (code says it should reference the secret)

## Current state inventory

**AWS:** account `926211191776`, region `us-east-1`, IAM user `learnlikemagic-admin`.

**What `terraform state list` shows (already imported, leave alone):**
```
data.aws_caller_identity.current
data.aws_region.current
data.aws_subnets.default
data.aws_vpc.default
module.database.aws_db_instance.database
module.database.aws_db_parameter_group.database
module.database.aws_db_subnet_group.database
module.database.aws_security_group.database
module.github_oidc.data.tls_certificate.github
module.secrets.aws_secretsmanager_secret.gemini_api_key
module.secrets.aws_secretsmanager_secret_version.gemini_api_key
```

**What production has (needs import):**

| Resource | Production identifier |
|---|---|
| App Runner service | `arn:aws:apprunner:us-east-1:926211191776:service/llm-backend-prod/3681f3cee2884f25842f6b15e9eacbfd` |
| App Runner auto-scaling config | name `llm-autoscale-production` |
| ECR repo | `learnlikemagic-backend-production` |
| ECR lifecycle policy | (attached to repo above) |
| IAM role: App Runner access | `learnlikemagic-apprunner-access-production` |
| IAM role: App Runner instance | `learnlikemagic-apprunner-instance-production` |
| IAM role: GitHub Actions | `learnlikemagic-github-actions-production` |
| Inline policies on instance role | `secrets-access`, `s3-books-access`, `anthropic-secret-access`, `cognito-admin`, `elevenlabs-secret-access` |
| Inline policies on github-actions role | 4 of them: apprunner, cloudfront, ecr, s3 |
| OpenIDC provider | GitHub Actions OIDC |
| Secrets: openai, db_password, anthropic, elevenlabs | `learnlikemagic-production-{openai,db-password,anthropic,elevenlabs}-api-key` (each + its `_version` sibling) |
| CloudFront distribution | `E19EYV4ZGTL1L9` (frontend), `E1YU1HKBGOFA8F` (other) |
| CloudFront cache policy | (one) |
| CloudFront function (SPA routing) | (one) |
| CloudFront origin access identity | (one) |
| S3 frontend bucket | `learnlikemagic-frontend-production` (+ bucket policy + public access block) |

**Code-vs-prod deltas that need code changes (not just imports):**

1. `modules/app-runner/main.tf` — `runtime_environment_variables` block in code is missing `COGNITO_APP_CLIENT_ID`, `COGNITO_REGION`, `COGNITO_USER_POOL_ID`. Add them as variables.
2. `modules/app-runner/main.tf` — `aws_iam_role_policy.app_runner_secrets` (named `secrets-access`) in prod has only `[openai_secret_arn]` in its Resource list, not `[openai, gemini, elevenlabs]` as the current code wants. Restructure: keep `secrets-access` as openai-only, add `anthropic-secret-access`, `elevenlabs-secret-access`, and `cognito-admin` as separate `aws_iam_role_policy` resources matching the live shape.
3. `modules/app-runner/main.tf` — `GOOGLE_CLOUD_TTS_API_KEY` is a plain-text env var in prod (`AIzaSyAxzPlvjlNEp4oiXng5sAiJvFZ8weMqXOw`); code currently maps it to `var.gemini_secret_arn` as a secret. Either flip the code to env-var (matches reality) or fix prod to use the secret reference. Pick whichever is cheaper; flagging as a separate secrets-hygiene issue regardless.
4. `modules/app-runner/main.tf` — `DATABASE_URL` is plain text with embedded password in prod (`postgresql://llmuser:preMJ12345$@learnlikemagic-production.cgp4ua06a7ei.us-east-1.rds.amazonaws.com:5432/learnlikemagic`). Same fix-or-document decision.
5. `modules/secrets/` — already has `elevenlabs_api_key` resource added on PR #138 branch. Confirm shape matches prod after import.
6. `modules/app-runner/variables.tf` — already has `elevenlabs_secret_arn` and `tts_provider` on PR #138 branch. Confirm.

## Approach: Path A — reconcile to zero diff

Goal: `terraform plan` shows `No changes` after this work. Future infra changes go through code review + `apply` like normal IaC.

### Order of operations (easiest first, build confidence)

1. **ECR (10 min)** — `aws_ecr_repository.backend` + `aws_ecr_lifecycle_policy.backend`. Two imports, code likely already correct.

2. **Standalone secrets (25 min)** — import `openai_api_key`, `db_password`, `anthropic_api_key[0]`, plus the new `elevenlabs_api_key[0]` from today's manual work, and each of their `_version` siblings.

   **Gotcha:** `aws_secretsmanager_secret_version` doesn't fully import the actual secret value via `terraform import`. After import, `terraform plan` will want to "update" the version to match `var.openai_api_key` from `terraform.tfvars`. Two options:
   - (a) Make sure `terraform.tfvars` has the actual current production values (read them from Secrets Manager via `aws secretsmanager get-secret-value`).
   - (b) Add `lifecycle { ignore_changes = [secret_string] }` to each `_version` resource. This means rotation must happen via console or CLI, not Terraform — but it's safer if you don't want Terraform to ever touch secret values.

3. **GitHub OIDC module (25 min)** — `aws_iam_openid_connect_provider.github`, `aws_iam_role.github_actions`, and the 4 inline policies on that role: `github_actions_apprunner`, `github_actions_cloudfront`, `github_actions_ecr`, `github_actions_s3`. Code likely already matches prod for this module — `terraform plan` after import is the easiest tell.

4. **App Runner module (50 min)** — the hardest. Import `aws_iam_role.app_runner_access`, `aws_iam_role.app_runner_instance`, `aws_iam_role_policy_attachment.app_runner_ecr`, `aws_iam_role_policy.app_runner_secrets`, `aws_iam_role_policy.app_runner_s3_books`, `aws_apprunner_auto_scaling_configuration_version.backend`, `aws_apprunner_service.backend`. **Plus** code restructure (see deltas #1, #2 above) — split `secrets-access` into multiple inline policies, add Cognito vars. The App Runner service has dozens of attributes; expect 3-5 iterations of `plan` → tweak code → `plan` to reach zero diff.

5. **Frontend module (40 min)** — `aws_s3_bucket.frontend`, `aws_s3_bucket_policy.frontend`, `aws_s3_bucket_public_access_block.frontend`, `aws_cloudfront_distribution.frontend`, `aws_cloudfront_cache_policy.frontend`, `aws_cloudfront_function.spa_routing`, `aws_cloudfront_origin_access_identity.frontend`. CloudFront distribution import is slowest (~30s). **Only import `E19EYV4ZGTL1L9`** (aliases `learnlikemagic.com` / `www.learnlikemagic.com`, origin `learnlikemagic-frontend-production.s3.us-east-1.amazonaws.com`). The other distribution `E1YU1HKBGOFA8F` is `www.mystorybuddy.com` — a separate project with `us-west-2` origins, **not ours, do not import**.

6. **Inline policies code-restructure (15 min)** — write the three additional `aws_iam_role_policy` resources for `cognito-admin`, `anthropic-secret-access`, `elevenlabs-secret-access` matching what's live, then import them.

### Per-step verification

After every module's imports + code adjustments:

```bash
terraform plan -target='module.<name>'
```

Should show `No changes`. If it shows changes, examine the diff:
- "destroy + create" on any resource = serious; aborts.
- "update in-place" on attributes that can't be set retroactively (e.g., name fields with `ForceNew`) = aborts.
- "update in-place" on benign attributes (tags, descriptions) = either fix the code to match live, or accept and `apply -target=...` for that single attribute.

Final acceptance gate: full `terraform plan` shows `No changes. Your infrastructure matches the configuration.`

### Safety guardrails

- **Backup the state file** before each module's import session: `cp terraform.tfstate terraform.tfstate.pre-<module>-$(date +%s)`. (3 historical backups already exist: `terraform.tfstate.backup`, `terraform.tfstate.backup-pre-migration` — leave them alone.)
- **Use `-target` everywhere** during reconciliation. Never run unscoped `apply`.
- **Don't apply mid-reconciliation** even if a `plan` shows what looks like a benign change — finish the module, get to zero diff, only then consider apply.
- **Read prod-DB-touching resources read-only**. State imports don't touch AWS resources, but writing the wrong attribute and then applying could (e.g., changing `name` triggers replace).

### Manual ops that happened today (2026-05-01) that need to be in code + state

These were executed via AWS CLI on 2026-05-01 during the EL cutover (see PR #138):

1. Created secret `learnlikemagic-production-elevenlabs-api-key` (ARN: `arn:aws:secretsmanager:us-east-1:926211191776:secret:learnlikemagic-production-elevenlabs-api-key-mfbB4s`).
2. Created inline policy `elevenlabs-secret-access` on role `learnlikemagic-apprunner-instance-production` granting `secretsmanager:GetSecretValue` on the EL ARN.
3. Updated App Runner service `llm-backend-prod`: added `TTS_PROVIDER=elevenlabs` to `runtime_environment_variables`; added `ELEVENLABS_API_KEY=<EL ARN>` to `runtime_environment_secrets`.

The PR #138 Terraform code adds these as resources, but they exist in prod and not in state — exactly the import case this reconciliation handles.

## Reference: where to find things

- **Repo:** `/Users/manishjain/repos/learnlikemagic`
- **Terraform dir:** `infra/terraform/`
- **State file:** `infra/terraform/terraform.tfstate` (gitignored, local only)
- **tfvars:** `infra/terraform/terraform.tfvars` (gitignored, contains real secret values)
- **Branch with EL cutover code:** `feat/tts-elevenlabs-impl` (PR #138, contains the ElevenLabs Terraform additions but not yet applied; safe baseline to start reconciliation from)
- **Main code module paths:**
  - `infra/terraform/main.tf` — root module wiring
  - `infra/terraform/variables.tf` — root vars
  - `infra/terraform/modules/{secrets,app-runner,database,ecr,frontend,github-oidc}/`
- **AWS CLI default profile** uses creds for `learnlikemagic-admin` (region `us-east-1`).

## Reference: useful commands

```bash
# Inventory live resources
aws apprunner list-services --region us-east-1
aws secretsmanager list-secrets --region us-east-1 --query 'SecretList[?starts_with(Name, `learnlikemagic`)].Name'
aws iam list-role-policies --role-name learnlikemagic-apprunner-instance-production
aws apprunner describe-service --service-arn <ARN> --region us-east-1

# State surgery
terraform state list
terraform state show <addr>
terraform state rm <addr>             # if you need to undo an import
terraform import <addr> <prod-id>     # canonical import command per resource

# Verification
terraform plan -target='module.X'
terraform plan                        # zero-diff acceptance gate
```

## What "done" looks like

1. `terraform state list` includes every prod resource (~30+ entries).
2. `terraform plan` shows `No changes. Your infrastructure matches the configuration.`
3. `infra/terraform/` code accurately documents production reality (Cognito vars, split inline policies, EL additions, plain-text vs secret-ref for Google TTS + DB password decided either way).
4. A short note added to this file (or a follow-up commit) recording the actual reconciliation result.
5. Future infra changes go via code review + `terraform plan` + `terraform apply` like normal.

After this work, deferred-but-related cleanups become available:
- Move `GOOGLE_CLOUD_TTS_API_KEY` from plain-text env to a secret reference.
- Move DB password out of `DATABASE_URL` and use a Secrets Manager reference + URL composition at app start.
- Configure an S3 backend for the Terraform state (with DynamoDB locking) so multiple people can apply safely.

## Decisions (resolved 2026-05-01)

1. **Google TTS key + DB password hygiene → defer.** Flip code to match prod's plain-text reality during this reconciliation; secret-reference cleanup is a separate follow-up (already listed under "deferred-but-related cleanups" above).
2. **`E1YU1HKBGOFA8F` → not ours.** Confirmed via `aws cloudfront get-distribution`: aliases `www.mystorybuddy.com`, origins in `us-west-2` — separate "My Story Buddy" project sharing the AWS account. Do not import. Only `E19EYV4ZGTL1L9` (the `learnlikemagic.com` distribution) belongs in this Terraform.
3. **S3 backend migration → later.** Keep local state during this pass; revisit as part of the deferred cleanups.
