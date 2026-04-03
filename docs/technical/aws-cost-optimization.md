# AWS Cost Optimization

Changes made on 2026-04-03 to reduce AWS spend from ~$103/mo to ~$18/mo.

---

## Before (March 2026 — $103.12/mo actual, offset by AWS credits)

| Service | Cost/mo | % | Details |
|---------|---------|---|---------|
| Aurora Serverless v2 | $46.72 | 45% | 0.5 ACU min idle @ $44.99 + I/O $1.72 |
| EC2 t3.medium | $30.95 | 30% | `my-story-buddy-server` — orphaned from old project |
| VPC Public IPv4 | $11.16 | 11% | 3 public IPs @ $3.72 each |
| App Runner | $10.67 | 10% | `llm-backend-prod` provisioned memory |
| EBS + Secrets Manager | $3.20 | 3% | 20GB gp3 + 4 secrets |
| Other | $0.42 | <1% | ECR, S3, CloudFront, SES |

## Changes Made

### 1. Terminated EC2 `my-story-buddy-server` (saved $34.67/mo)

- Instance `i-068f140bc18b8a8b6` (t3.medium, us-east-1) — running since June 2025
- Tagged `Application: MyStoryBuddy`, separate VPC, own security group
- Confirmed not used by LearnLikeMagic: different VPC, no IAM role, no code references
- Savings: $30.95 compute + $1.60 EBS + $3.72 public IP = **$34.67/mo**

### 2. Migrated Aurora Serverless v2 to RDS db.t4g.micro (saved $46.72/mo)

**Why:** Aurora Serverless v2 at 0.5 ACU minimum costs ~$45/mo just idling. For a low-traffic app, standard RDS on free tier is sufficient.

**Migration steps executed:**
1. Created Aurora cluster snapshot (`learnlikemagic-pre-migration-20260403`)
2. Ran `pg_dump` of full database (schema + data, 4.5MB, 23 tables)
3. Recorded row counts for all tables as verification baseline
4. Deleted orphaned MySQL `database-1` in us-west-2 (freed RDS free tier slot)
5. Updated Terraform database module (`infra/terraform/modules/database/main.tf`):
   - Replaced `aws_rds_cluster` + `aws_rds_cluster_instance` with `aws_db_instance`
   - Changed parameter group family from `aurora-postgresql15` to `postgres15`
   - Updated outputs to reference `aws_db_instance.database`
6. Imported existing security group and subnet group into Terraform state
7. Applied Terraform with `-target=module.database` to create new RDS instance only
8. Restored `pg_dump` to new instance with `pg_restore --no-owner --no-privileges`
9. Verified all 23 table row counts match exactly
10. Updated App Runner `DATABASE_URL` via AWS CLI `update-service`
11. Verified all 24 API endpoints return correct data
12. Deleted Aurora cluster and instance after verification

**Key compatibility finding:** No Aurora-specific SQL in the codebase. The most advanced PostgreSQL feature used is `DISTINCT ON`, which is standard PostgreSQL. Both engines run PostgreSQL 15.

**New database spec:**
- Instance: `learnlikemagic-production` (db.t4g.micro)
- Engine: PostgreSQL 15
- 2 vCPU, 1GB RAM, 20GB gp2 storage
- Free tier eligible (750 hours/month for 12 months)
- Same VPC, security group, subnet group as before

### 3. Deleted orphaned MySQL `database-1` (saved $3.72/mo)

- Instance in us-west-2, db.t4g.micro, MySQL 8.0.42
- Created June 2025 for MyStoryBuddy — no references in LearnLikeMagic codebase
- Consuming the RDS free tier slot (750 hours shared across all engines)
- Deleted to free up free tier for the new PostgreSQL instance

## After (~$18/mo)

| Service | Cost/mo | Notes |
|---------|---------|-------|
| App Runner | $10.67 | Unchanged — provisioned memory for `llm-backend-prod` |
| VPC Public IPv4 | $3.72 | 1 IP for new RDS instance (was 3, now 1) |
| Secrets Manager | $1.60 | 4 secrets @ $0.40 |
| RDS db.t4g.micro | $0 | Free tier (12 months from account creation) |
| Other | ~$2 | ECR, S3, EBS |

**Total savings: ~$85/mo (83% reduction)**

After free tier expires (~June 2026): db.t4g.micro costs ~$12.41/mo, bringing total to ~$30/mo.

## Backups & Rollback

- Aurora snapshot `learnlikemagic-pre-migration-20260403` retained for 30 days
- Local pg_dump file: `learnlikemagic-backup-20260403.dump`
- Terraform state backup: `infra/terraform/terraform.tfstate.backup-pre-migration`

## Files Modified

| File | Change |
|------|--------|
| `infra/terraform/modules/database/main.tf` | Aurora cluster/instance replaced with RDS db_instance |
| `infra/terraform/modules/database/outputs.tf` | Outputs reference db_instance instead of cluster |
| `infra/terraform/outputs.tf` | `cluster_endpoint` renamed to `instance_endpoint` |
| `infra/terraform/main.tf` | Comment updated |
