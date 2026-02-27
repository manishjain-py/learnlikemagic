# Ops And Testing Runbook

Last audited: 2026-02-27
Code baseline: `claude/update-ai-agent-files-ulEgH@212063c`

## Local Backend
```bash
cd llm-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python db.py --migrate
make run
```

## Local Frontend
```bash
cd llm-frontend
npm install
npm run dev
```

## Local Compose
```bash
docker-compose up --build
```

## Backend Command Surface
```bash
cd llm-backend
make help
make run
make test
make db-migrate
make build-local
make run-docker
make build-prod
make push
make deploy
make check-arch
make clean
make ecr-login
make tag-ecr
```

## Frontend Command Surface
```bash
cd llm-frontend
npm run dev
npm run build
npm run preview
npm run test
npm run test:watch
```

## E2E Command Surface
```bash
cd e2e
npm install
npx playwright install
npm test
npm run test:headed
npm run test:ui
npm run report
```

## Test Inventory
- Backend unit test files: `50`
- Backend integration test files: `8` (7 test files + 1 test data helper)
- Frontend test files: `1` (vitest + testing-library)
- E2E runner: `e2e/tests/scenarios.spec.ts`
- E2E scenario source: `e2e/scenarios.json`
- E2E outputs: `reports/e2e-runner/`

## CI Workflows
- `daily-coverage.yml`: daily unit coverage + HTML + email + artifact
- `deploy-backend.yml`: build amd64 image, push ECR, trigger App Runner
- `deploy-frontend.yml`: build and deploy frontend to S3+CloudFront
- `manual-deploy.yml`: manual frontend/backend/both deploy paths

## Infra Entrypoints
- Root terraform: `infra/terraform/main.tf`
- Terraform docs: `infra/terraform/README.md`

## Deployment Notes
- App Runner expects `linux/amd64`; backend production build must target amd64.
- Backend deploy workflow copies `docs/` and `e2e/scenarios.json` into backend build context.
