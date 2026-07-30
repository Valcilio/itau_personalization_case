# SOLUTION — Personalization Service

Documento de entrega do case técnico. Descreve o que foi construído, como executar, decisões tomadas e limitações conhecidas.

---

## Visão geral

A solução separa **treino**, **predição em batch** e **serving HTTP** em três aplicações Python, todas containerizadas e deployadas na AWS via Terraform:

| Aplicação | Papel |
|-----------|--------|
| `model_train` | Treina o classificador sklearn, faz seed do `model.pkl` do case como v1 no Registry (se vazio), publica artefato no S3 e registra a versão treinada como próxima |
| `model_predict` | Gera scores para todos os pares usuário×produto, grava snapshot no S3 e substitui a tabela DynamoDB (usa sempre a versão do modelo que foi dada para o case) |
| `recommendations_api` | API REST síncrona que lê predições pré-computadas e responde em tempo de requisição |

**Por que batch + API leve?** O modelo scoreia ~30k pares (500 usuários × 60 produtos) por execução. Rodar feature engineering + inferência a cada `GET` aumentaria latência (centenas de ms a segundos) e custo. A API consulta DynamoDB (single-digit ms na leitura) e mantém o contrato síncrono exigido pelo case.

### Arquitetura na AWS

<p align="center">
  <img src="https://i.imgur.com/dm47Hfh.png" alt="Diagrama de arquitetura — Personalization Service na AWS" width="680" />
</p>

O fluxo completo, da esteira de CI/CD até a resposta síncrona ao usuário:

| Camada | Componentes | Responsabilidade |
|--------|-------------|------------------|
| **Code Versioning** | GitHub (repo + Actions CI/CD) | CI: `pytest` + `pylint`, tag de versão e build da imagem Docker. CD: `terraform apply`, push para ECR, testes de integração AWS e rollback se falhar |
| **Continuous Training** | ECS `model_train` | Executa o pipeline de treino; seed do modelo do case (v1) se o Registry estiver vazio; registra retreino como v2, v3…; disparado via `null_resource` após integração na CI |
| **Model Versioning** | SageMaker Model Registry + S3 (`models/`) | Versiona e aprova model packages; v1 = artefato original do case; demais versões = retreinos |
| **Data Dependency** | S3 (`training-data/`) | `events.csv` e `products.csv` — dependência compartilhada entre treino e predição |
| **Prediction** | ECS `model_predict` → S3 + DynamoDB | Batch: calcula scores, registra predições/features no S3 e grava último snapshot no DynamoDB; disparado via `null_resource` após train na CI |
| **Endpoint (serving)** | API Gateway → VPC Link → **NLB → ALB** → ECS `recommendations_api` | Resposta **síncrona**: ECS lê últimas predições do DynamoDB; cold start via `products.csv` no S3 |
| **Monitoring** | CloudWatch Logs + `/metrics` (in-memory) | Logs de infraestrutura e aplicação; métricas Prometheus expostas pelo container |

Rotas expostas via API Gateway (autenticação por `x-api-key`, exceto `/health`):

- `GET /health`
- `GET /recommendation/{user_id}` e `GET /recommendations/{user_id}`
- `POST /recommendation_filtered` e `POST /recommendations_filtered`
- `GET /metrics`

Pipeline de deploy (GitHub → AWS) — detalhes em [Pipeline CI/CD](#pipeline-cicd-github-actions):

```
push → CI (pylint + unit tests)
     → tag release (v0.1.N em main, UAT nas demais)
     → terraform apply (infra)
     → push imagens ECR
     → integration tests (AWS real)
     → trigger model_train (ECS RunTask, só se integração passar)
     → wait 10s
     → trigger model_predict (ECS RunTask)
     → rollback Terraform (se integração falhar)
```

---

## Como rodar o projeto

### Pré-requisitos

- Python **≥ 3.12**
- Docker (opcional, recomendado para paridade com produção)
- AWS CLI + credenciais (apenas para deploy e testes de integração)
- Terraform **≥ 1.9** (deploy de infra)

### Instalação local

```bash
git clone <repo>
cd personalization_case
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Testes unitários (padrão, sem AWS)

```bash
pytest                    # 118 testes, ~1s
pylint src                # lint do código de produção
```

Testes de integração são **excluídos** do `pytest` padrão (`-m "not integration"`).

### Testes de integração (AWS real)

Requer infra aplicada e credenciais configuradas:

```bash
cd terraform
terraform init
terraform apply -var="image_tag=UAT" -var="aws_region=us-east-1"

cd ..
pytest tests/integration -m integration -s
```

Ordem enforced: `model_train` → `model_predict` → `recommendations_api`.  
O teste da API exige predições no DynamoDB (geradas pelo `model_predict`).

Os testes de integração **não alteram recursos de produção**:
- `model_train` registra versões em `integration_model_package_group_name` (não no Model Group de produção).
- `model_predict` e `recommendations_api` usam `integration_predictions_dynamodb_table_name` (tabela DynamoDB separada).

> **Nota:** `model_predict` em produção substitui ~30k linhas no DynamoDB e pode levar **vários minutos**. O teste de integração escreve na tabela isolada com o mesmo volume.

### API local (sem ECS)

Com variáveis apontando para recursos AWS já existentes:

```bash
export AWS_REGION=us-east-1
export DATA_BUCKET=<terraform output data_bucket_name>
export PREDICTIONS_DYNAMODB_TABLE=<terraform output predictions_dynamodb_table_name>

PYTHONPATH=src uvicorn recommendations_api.main:app --host 0.0.0.0 --port 8080
```

Endpoints locais:

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Liveness |
| `GET` | `/metrics` | Métricas Prometheus 0.0.4 |
| `GET` | `/recommendations/{user_id}` | Top-N recomendações (N=10) |
| `POST` | `/recommendations_filtered` | Recomendações com filtros |

### Pipelines batch locais

```bash
# Treino (seed do model.pkl do case como v1 se Registry vazio + retreino como próxima versão)
export DATA_BUCKET=... MODEL_BUCKET=... MODEL_PACKAGE_GROUP_NAME=...
export INFERENCE_IMAGE_URI=... IMAGE_TAG=local-dev
# opcional: BASELINE_MODEL_DIR=./model BASELINE_MODEL_PREFIX=models/purchase_propensity/case-baseline-v1
PYTHONPATH=src python -m model_train.main

# Predição (lê CSVs do S3, escreve DynamoDB)
export PREDICTIONS_DYNAMODB_TABLE=...
PYTHONPATH=src python -m model_predict.main
```

O JSON de saída do treino inclui `baseline_model_package_arn` quando o seed ocorreu na execução (caso contrário, `null`).

### Docker

```bash
docker build -f docker/recommendations_api/Dockerfile -t recommendations-api .
docker build -f docker/model_predict/Dockerfile -t model-predict .
docker build -f docker/model_train/Dockerfile --build-arg IMAGE_TAG=local-dev -t model-train .
```

A imagem `model-train` inclui o diretório `model/` em `/app/model` (`BASELINE_MODEL_DIR` padrão) para o seed automático do artefato original do case.

### Deploy na AWS (produção)

O deploy é automatizado pelo GitHub Actions. Detalhes completos nas seções [Pipeline CI/CD](#pipeline-cicd-github-actions) e [Infraestrutura Terraform](#infraestrutura-terraform).

Resumo:

1. **CI** — pylint + pytest unitário (PR e push)
2. **CD** (somente push, não PR):
   - `terraform apply` (infra, sem disparar predict)
   - push das 3 imagens para ECR
   - testes de integração AWS
   - **trigger `model_train`** no ECS (somente após integração passar)
   - **wait 10s** antes do predict
   - **trigger `model_predict`** no ECS
   - rollback automático do Terraform se integração falhar

Secrets necessários no repositório: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`.

Endpoint público (após deploy):

```bash
terraform output -raw recommendations_api_gateway_endpoint   # ex: .../v1
terraform output -raw recommendations_api_key                # header x-api-key
```

Exemplo:

```bash
curl -H "x-api-key: $API_KEY" "$ENDPOINT/recommendations/u_0231"
curl -H "x-api-key: $API_KEY" "$ENDPOINT/metrics"
```

---

## Pipeline CI/CD (GitHub Actions)

A esteira está em `.github/workflows/` e é orquestrada por `workflow.yaml` (**Personalization CI/CD**).

### Gatilhos

| Evento | CI (lint + testes) | CD (deploy AWS) |
|--------|-------------------|-----------------|
| `pull_request` | ✅ | ❌ |
| `push` (qualquer branch) | ✅ | ✅ |
| `workflow_dispatch` | ✅ | ✅ (se não for PR) |

### Visão geral dos workflows

| Arquivo | Papel |
|---------|--------|
| `workflow.yaml` | Orquestrador principal — encadeia CI → tag → CD |
| `pylint_and_pytest.yaml` | `pylint src` + `pytest -m "not integration"` |
| `cicd_general.yaml` | Resolve `image_tag` e cria git tag em `main` |
| `terraform_docker.yaml` | Terraform apply, push ECR, integração, train, predict, rollback |
| `integration_tests.yaml` | `pytest tests/integration -m integration` (timeout 90 min) |

### Fluxo completo (push)

```
workflow.yaml
  │
  ├─ 1. ci-quality ────────────── pylint + pytest unitário (~118 testes)
  │
  ├─ 2. ci-tag-release ────────── só se push (não PR)
  │       • main  → image_tag = v0.1.{run_number} + git tag
  │       • outras branches → image_tag = UAT
  │
  └─ 3. cd-docker-and-terraform ─ só se push (não PR)
          │
          ├─ deploy-terraform
          │     • backup do state (artifact para rollback)
          │     • terraform validate + plan + apply
          │     • run_model_train_on_apply=false
          │     • run_model_predict_on_apply=false  ← não roda batch ainda
          │
          ├─ push-model-train-image      ─┐
          ├─ push-model-predict-image    ─┼─ paralelo (após terraform)
          └─ push-recommendations-api-image ─┘
          │
          ├─ integration-tests ────────── model_train → model_predict → API
          │     (usa recursos de integração isolados — ver Terraform)
          │
          ├─ trigger-model-train ──────── só se integração passou
          │     • terraform apply -target=null_resource.run_model_train_on_apply
          │     • run_model_train_on_apply=true → ECS RunTask
          │
          ├─ trigger-model-predict ────── após train (+ sleep 10s no início)
          │     • sleep 10 — margem para o task de treino iniciar
          │     • terraform apply -target=null_resource.run_model_predict_on_apply
          │     • run_model_predict_on_apply=true → ECS RunTask
          │
          └─ rollback-terraform ───────── só se integração falhou
                • restaura state do backup pré-apply
                • terraform apply com image_tag anterior (rollback_image_tag)
```

### Decisões importantes da pipeline

**Terraform antes das imagens.** O `apply` inicial cria/atualiza ECR, ECS, IAM, etc. As imagens Docker referenciam repositórios que já existem. O `image_tag` da pipeline é passado como variável Terraform e compõe as URIs das task definitions (`local.*_image_uri`).

**Batch jobs só após integração.** `model_train` e `model_predict` em produção só disparam se os testes de integração passarem. O treino roda primeiro; aguarda-se **10 segundos** (`sleep 10`) antes do predict, dando margem para o ECS RunTask de treino ser aceito pela API (o job não espera o treino terminar — apenas evita disparo simultâneo). Se a integração falha, nenhum batch roda e o state Terraform é revertido.

**Rollback limitado.** O rollback restaura o **state Terraform** e reconcilia a infra com a tag de imagem anterior. Dados já escritos (S3, DynamoDB, Registry) durante testes de integração **não** são revertidos automaticamente.

**Cache Docker.** Buildx usa cache `type=gha` por serviço (`scope=model-train`, etc.) para acelerar rebuilds.

### Secrets e permissões

| Secret | Uso |
|--------|-----|
| `AWS_ACCESS_KEY_ID` | Credencial CI para Terraform, ECR, ECS, testes |
| `AWS_SECRET_ACCESS_KEY` | Par da credencial acima |
| `AWS_REGION` | Região (ex.: `us-east-1`) — passada como `var.aws_region` |

O job de tag/release precisa `contents: write` para criar git tags em `main`.

### Tags de imagem

| Branch | `image_tag` | Tag git |
|--------|-------------|---------|
| `main` | `v0.1.{run_number}` | criada automaticamente |
| demais | `UAT` | não cria tag |

Em `main`, também publica `:latest` nos três repositórios ECR (`push_latest: true`).

### O que roda em PR

Apenas **CI Quality**: pylint + testes unitários. Nenhum deploy, integração AWS ou alteração de infra.

---

## Infraestrutura Terraform

Código em `terraform/`. Provisiona toda a stack AWS do case: storage, batch jobs, API pública e recursos isolados para testes de integração.

### Backend remoto e bootstrap

O state principal fica em **S3** com lock **DynamoDB** (`terraform/versions.tf`):

| Config | Valor |
|--------|--------|
| Bucket | `personalization-terraform-state-{account_id}` |
| Key | `terraform/state/model-train/terraform.tfstate` |
| Lock table | `personalization-terraform-locks` |
| Região | `us-east-1` |

O bootstrap (`terraform/bootstrap/`) cria bucket + tabela de lock **uma única vez**, antes do primeiro `terraform init` do stack principal:

```bash
cd terraform/bootstrap
terraform init && terraform apply
cd ../..
cd terraform
terraform init   # usa backend remoto configurado em versions.tf
```

### Mapa de arquivos

| Arquivo | Recursos principais |
|---------|---------------------|
| `versions.tf` | Backend S3, provider AWS, versões |
| `variables.tf` | Parâmetros (`image_tag`, CPU/memória ECS, etc.) |
| `locals.tf` | URIs de imagem ECR, env vars dos containers |
| `outputs.tf` | Endpoints, buckets, ARNs, comandos `ecs run-task` |
| `s3.tf` | Buckets `data` e `models`; upload de `events.csv` / `products.csv` |
| `dynamodb.tf` | Tabela produção + tabela de integração |
| `ecr.tf` | 3 repositórios ECR + lifecycle (mantém 10 imagens) |
| `iam.tf` | Roles ECS task/execution — S3, DynamoDB, SageMaker, logs |
| `cloudwatch.tf` | Log groups por serviço |
| `sagemaker_model_registry.tf` | Model groups produção + integração |
| `ecs_model_train.tf` | Cluster + task definition + `null_resource` RunTask |
| `ecs_model_predict.tf` | Cluster + task definition + `null_resource` RunTask |
| `ecs_recommendations_api.tf` | ALB interno, NLB, ECS service, autoscaling |
| `api_gateway_recommendations.tf` | REST API pública, VPC Link, API key, stage `v1` |

### Diagrama lógico dos recursos

```
                    ┌─────────────────────────────────────┐
                    │         API Gateway (REST)          │
                    │  /health  /recommendations/*  ... │
                    └──────────────┬──────────────────────┘
                                   │ VPC Link
                    ┌──────────────▼──────────────────────┐
                    │   NLB → ALB (interno) → ECS Fargate │
                    │      recommendations_api            │
                    └──────────────┬──────────────────────┘
                                   │ lê
                    ┌──────────────▼──────────────────────┐
                    │   DynamoDB (predictions)            │
                    └──────────────▲──────────────────────┘
                                   │ escreve
                    ┌──────────────┴──────────────────────┐
                    │   ECS Fargate — model_predict       │
                    │   (RunTask via null_resource)       │
                    └──────────────▲──────────────────────┘
                                   │ lê modelo v1
                    ┌──────────────┴──────────────────────┐
                    │   SageMaker Model Registry          │
                    └──────────────▲──────────────────────┘
                                   │ registra
                    ┌──────────────┴──────────────────────┐
                    │   ECS Fargate — model_train         │
                    └─────────────────────────────────────┘

        S3 data bucket ◄── events.csv, products.csv, predictions/
        S3 models bucket ◄── model.tar.gz, artefatos de treino
        ECR ◄── 3 imagens Docker (tag = var.image_tag)
```

### Variáveis principais

| Variável | Obrigatória | Default | Efeito |
|----------|-------------|---------|--------|
| `image_tag` | **sim** | — | Tag Docker em ECR e task definitions |
| `aws_region` | não | `us-east-1` | Região de deploy |
| `project_name` | não | `personalization` | Prefixo de nomes de recursos |
| `run_model_train_on_apply` | não | `true` | Se `true`, `null_resource` dispara ECS RunTask de treino no apply |
| `run_model_predict_on_apply` | não | `true` | Se `true`, `null_resource` dispara ECS RunTask de predict no apply |
| `training_data_prefix` | não | `training-data` | Prefixo S3 dos CSVs |
| `predictions_prefix` | não | `predictions` | Prefixo S3 das predições |
| `ecs_task_cpu` / `memory` | não | 4096 / 8192 | Batch train/predict |
| `model_package_group_name` | não | `purchase-propensity-model-group` | Registry produção |

Na CI, o apply inicial usa `run_model_train_on_apply=false` e `run_model_predict_on_apply=false`. Após integração: job `trigger-model-train` (apply targeted com train=true), depois `trigger-model-predict` (sleep 10s + apply targeted com predict=true).

### Recursos de integração (isolados)

Para não poluir produção durante os testes de integração:

| Recurso produção | Recurso de integração | Output Terraform |
|------------------|----------------------|------------------|
| `personalization-predictions` (DynamoDB) | `personalization-integration-predictions` | `integration_predictions_dynamodb_table_name` |
| `purchase-propensity-model-group` (SageMaker) | `personalization-integration-model-group` | `integration_model_package_group_name` |

Os testes em `tests/helpers/aws_integration.py` leem esses outputs e apontam `model_train` / `model_predict` / API para os recursos de integração.

### `null_resource.run_model_train_on_apply` e `run_model_predict_on_apply`

Cada um dispara um **ECS RunTask** one-shot via `local-exec` + AWS CLI quando a variável correspondente é `true`.

| Recurso | Serviço | Quando na CI |
|---------|---------|--------------|
| `null_resource.run_model_train_on_apply` | `model_train` | Job `trigger-model-train`, após integração |
| `null_resource.run_model_predict_on_apply` | `model_predict` | Job `trigger-model-predict`, após train + `sleep 10` |

Comportamento comum:

- **Triggers:** `task_definition_arn` + `image_tag` — reexecuta se a task definition ou tag mudarem.
- **CI:** apply `-target=null_resource.*` com a flag daquele job em `true` e a outra em `false`.
- **Apply local padrão:** ambas com `default = true` — cuidado ao rodar `terraform apply` manualmente.

Comandos equivalentes manuais:

```bash
terraform output -raw model_train_ecs_run_task_command
terraform output -raw model_predict_ecs_run_task_command
```

### Outputs úteis

```bash
# API pública
terraform output -raw recommendations_api_gateway_endpoint
terraform output -raw recommendations_api_key

# Storage
terraform output -raw data_bucket_name
terraform output -raw models_bucket_name
terraform output -raw predictions_dynamodb_table_name

# Integração
terraform output -raw integration_predictions_dynamodb_table_name
terraform output -raw integration_model_package_group_name

# Imagens
terraform output -raw model_train_image_uri
terraform output -raw model_predict_image_uri
terraform output -raw recommendations_api_image_uri
```

### Apply manual (fora da CI)

```bash
cd terraform
terraform init
terraform plan  -var="image_tag=UAT" -var="run_model_train_on_apply=false" -var="run_model_predict_on_apply=false"
terraform apply -var="image_tag=UAT" -var="run_model_train_on_apply=false" -var="run_model_predict_on_apply=false"

# build + push imagens manualmente para ECR, depois:
terraform apply -var="image_tag=UAT" \
  -var="run_model_train_on_apply=true" \
  -var="run_model_predict_on_apply=false" \
  -target=null_resource.run_model_train_on_apply

sleep 10

terraform apply -var="image_tag=UAT" \
  -var="run_model_predict_on_apply=true" \
  -var="run_model_train_on_apply=false" \
  -target=null_resource.run_model_predict_on_apply
```

Após o apply, faça upload dos CSVs se necessário (Terraform já provisiona `events.csv` e `products.csv` do diretório `data/` no bucket).

### IAM (resumo)

A role `ecs_task` compartilhada pelos três serviços permite:

- **S3** — leitura/escrita nos buckets `data` e `models`
- **DynamoDB** — CRUD nas tabelas produção e integração
- **SageMaker** — criar/describe model packages e groups
- **ECR** — pull (via execution role) e validação pelo Registry
- **CloudWatch Logs** — escrita nos log groups dos serviços

---

## Endpoints e contratos

### `GET /recommendations/{user_id}`

Retorna até **10 produtos** ranqueados por `recommendation_score` (probabilidade de compra do modelo).

```json
{
  "user_id": "u_0231",
  "count": 10,
  "cold_start_flag": false,
  "recommendations": [
    {"product_id": "p_0042", "score": 0.67, "rank": 1}
  ]
}
```

### `POST /recommendations_filtered`

Body JSON com filtros opcionais: `limit`, `exclude_product_ids`, `category`, `categories`, `exclude_categories`, `min_price`, `max_price`, `min_avg_rating`, `min_popularity_score`, `min_recommendation_score`, `only_affinity_match`, `exclude_cold_start`.

Resposta inclui metadados enriquecidos (`category`, `price`, etc.) além do score.

### Autenticação

Na AWS, API Gateway exige header `x-api-key` em todas as rotas exceto `/health`.

---

## Preparação de features e `user_affinity_match`

Implementação em `model_predict/domain/usecases/featureengineer.py` (espelhada no treino em `model_train`):

1. **Pares usuário×produto:** produto cartesiano de usuários distintos em `events.csv` × catálogo em `products.csv`.
2. **`interactions`:** contagem de eventos por `(user_id, product_id)`; `0` se ausente.
3. **`price`, `avg_rating`, `popularity_score`:** join com `products.csv`.
4. **`user_affinity_match`:**
   - Join de eventos do usuário com categorias dos produtos.
   - Contagem de interações por `(user_id, category)`.
   - Categoria com **maior contagem** vira `top_affinity_category`.
   - **Desempate:** ordem alfabética de `category` (critério determinístico, documentado).
   - `user_affinity_match = 1` se `product.category == top_affinity_category`, senão `0`.

Features são validadas via entidades (`Costumer` / `Customer`) antes de escalar e inferir. O scaler e o modelo consomem matrizes **numpy** (sem nomes de colunas) para compatibilidade com o artefato original (`scikit-learn>=1.8.0,<1.9.0`).

---

## SageMaker Model Registry e seed do modelo baseline

O README do case entrega um **`model/model.pkl` já treinado** e deixa explícito que o foco não é retreinar ou melhorar o modelo. Mesmo assim, o pipeline `model_train` existe para demonstrar continuous training. Para conciliar os dois mundos, o treino **bootstrapa o Registry** com o artefato original antes de registrar qualquer retreino.

### Fluxo por execução

```
model_train.run_training_pipeline()
  │
  ├─ 1. has_model_packages(group)? 
  │      └─ NÃO (Registry vazio)
  │           → upload model/model.pkl (+ model_card.json) para S3
  │           → create_model_package → versão 1 (baseline do case)
  │      └─ SIM → pula seed
  │
  ├─ 2. download events.csv / products.csv (S3)
  ├─ 3. treina LogisticRegression + StandardScaler
  ├─ 4. upload artefato treinado para S3 (prefixo por IMAGE_TAG)
  └─ 5. create_model_package → versão 2, 3, 4… (conforme histórico do group)
```

O SageMaker incrementa `ModelPackageVersion` automaticamente a cada `create_model_package`. Na **primeira execução** em um group vazio, a mesma run produz:

| Versão | Origem | Descrição |
|--------|--------|-----------|
| **1** | `model/model.pkl` do repositório | Modelo fornecido no case; metadata `purchase_propensity_v1` |
| **2** | Retreino da execução atual | Novo fit sobre `events.csv` / `products.csv`; metadata `purchase_propensity_{IMAGE_TAG}` |

Nas execuções seguintes (Registry já populado), apenas o retreino é registrado (v3, v4…).

### Onde está o código

| Peça | Arquivo |
|------|---------|
| Orquestração do seed | `src/model_train/main.py` → `seed_baseline_model_if_needed()` |
| Resolução do diretório local | `resolve_baseline_model_dir()` — `BASELINE_MODEL_DIR`, `/app/model` ou `model/` na raiz do repo |
| Extração de `model.tar.gz` | `prepare_baseline_model_dir()` — usado se só o tarball existir |
| Checagem de versões existentes | `src/model_train/domain/gateways/awsconnector.py` → `has_model_packages()` |
| Upload + registro | `upload_model_directory()` + `register_model_package()` (reutilizados pelo fluxo normal) |

### Artefato baseline e container

- Diretório esperado: `model/model.pkl` e, opcionalmente, `model/model_card.json`.
- A imagem Docker de treino copia `model/` para `/app/model` e define `BASELINE_MODEL_DIR=/app/model`.
- O artefato baseline sobe para S3 em `BASELINE_MODEL_PREFIX` (default `models/purchase_propensity/case-baseline-v1`), separado do prefixo versionado por `IMAGE_TAG` usado no retreino.

### Relação com `model_predict`

`model_predict` continua consumindo **`HARDCODED_MODEL_PACKAGE_VERSION = 1`** — ou seja, sempre o pacote baseline do case em produção, alinhado ao requisito do README. As versões 2+ ficam disponíveis no Registry para auditoria, comparação offline ou futura promoção de modelo, mas **não entram no serving** neste case.

### Saída do pipeline

Além dos campos já existentes, o JSON final do treino expõe:

```json
{
  "model_version": "integration-20260729120000-abc12345",
  "model_s3_uri": "s3://.../models/purchase_propensity/integration-.../model.tar.gz",
  "model_package_arn": "arn:aws:sagemaker:...:model-package/.../2",
  "baseline_model_package_arn": "arn:aws:sagemaker:...:model-package/.../1",
  "accuracy": "0.85",
  "roc_auc": "0.91",
  "validated_customers": 7999
}
```

`baseline_model_package_arn` é `null` quando o seed foi ignorado (Registry já tinha versões ou S3/ECR não configurados).

### Quando o seed é ignorado

- O Model Package Group **já possui** ao menos uma versão (`has_model_packages` → true).
- `MODEL_BUCKET` ou `INFERENCE_IMAGE_URI` não estão configurados (mesma regra do registro normal).
- Em testes de integração, o group `integration_model_package_group_name` é isolado do de produção; após a primeira run bem-sucedida, execuções posteriores só registram retreinos.

---

## Cold start

**Cenário:** `user_id` sem linhas na tabela de predições (usuário ausente de `events.csv` ou ainda não scoreado).

**Estratégia:** fallback por **popularidade global**.

1. API consulta DynamoDB por `user_id`.
2. Se vazio → carrega `products.csv` do S3 (cache in-process com `@lru_cache`).
3. Retorna top-N produtos ordenados por `popularity_score`.
4. `recommendation_score` = `popularity_score`; `cold_start_flag: true` na resposta.
5. Logs registram `cold_start_fallback_selected`.

**Trade-off:** simples, determinístico e explicável — se não há histórico personalizado, o usuário recebe os produtos mais populares. Com mais contexto (sazonalidade, perfil demográfico, canal), dá para evoluir a estratégia sem mudar o contrato da API.

---

## Decisões de arquitetura e trade-offs

### 1. Batch predict + DynamoDB em vez de inferência online

| Prós | Contras |
|------|---------|
| Latência baixa e previsível na API | Predições ficam stale até próximo batch |
| Custo de inferência concentrado em job agendado | Novos usuários/produtos só aparecem após re-run |
| Escala horizontal da API sem carregar sklearn | Tabela grande (~30k+ itens) no replace completo |

O replace completo do DynamoDB é aceitável neste case (dados estáticos). Em produção, predições e writes deveriam ser incrementais.

### 2. Três apps separadas

Isola responsabilidades e permite escalar/versionar treino, batch e API independentemente. Custo: mais imagens Docker, mais Terraform e mais superfície operacional.

### 3. Clean Architecture

Cada app segue `domain/entities`, `domain/usecases`, `domain/gateways`, `main.py`. Isso separa regras de negócio de integrações externas e facilita testes unitários (mocks nos gateways) e de integração (AWS real nas bordas).

### 4. SageMaker Model Registry

Resumo: seed automático do `model.pkl` do case como **v1** quando o Registry está vazio; retreinos entram como **v2+**. Detalhes completos na seção [SageMaker Model Registry e seed do modelo baseline](#sagemaker-model-registry-e-seed-do-modelo-baseline).

`model_predict` consome **versão fixa 1** (`HARDCODED_MODEL_PACKAGE_VERSION = 1`): requisito do case. Em produção real, a versão servida viria de política de promoção no Registry.

### 5. Métricas in-memory + logs estruturados

Contadores e latências ficam in-memory e alimentam `/metrics` via `prometheus_client`. Cada request emite `api_request_metric`; cada scrape de `/metrics` emite `api_metrics_snapshot` — ambos recuperáveis no CloudWatch Logs Insights.

### 6. CI/CD com gate de integração

Testes AWS rodam **após** `terraform apply` e **push das imagens** para o ECR; `model_train` e `model_predict` em produção só disparam se a integração passar (train → sleep 10s → predict). Falha na integração → rollback do state Terraform. Ver [Pipeline CI/CD](#pipeline-cicd-github-actions) e [Infraestrutura Terraform](#infraestrutura-terraform).

### 7. API síncrona (e caminho assíncrono futuro)

O case exige resposta síncrona; a arquitetura prioriza latência baixa na leitura — batch de inferência + DynamoDB é uma das alavancas principais.

Em escala Itaú, se a inferência passasse a ocorrer em tempo de request, faria sentido evoluir para uma **API assíncrona**:

- **Resposta imediata** com `request_id`, sem bloquear até o fim da inferência; o cliente consulta o resultado depois.
- **Fila FIFO** absorve picos, serializa processamento e simplifica retries em falhas transientes.
- **Backpressure explícito** — limitar concorrência na fila torna o scaling mais previsível sob carga máxima.

---

## Testes

### Unitários (`tests/`, espelha `src/`)

- **118 testes** cobrindo feature engineering, handlers, filtros, cold start, métricas, gateways e seed do modelo baseline (mocks boto3/sklearn).
- Execução rápida (~1s), roda em todo PR.

### Integração (`tests/integration/`)

Três testes **sem mocks**, contra AWS real:

| Ordem | Teste | Valida |
|-------|-------|--------|
| 1 | `model_train` | Pipeline de treino → seed baseline (se Registry vazio) → S3 + SageMaker Registry (grupo de integração) |
| 2 | `model_predict` | Pipeline completo → S3 + DynamoDB (tabela de integração) |
| 3 | `recommendations_api` | `TestClient` + conectores reais (tabela DynamoDB de integração, S3, métricas) |

O teste da API exercita HTTP de ponta a ponta (`TestClient` → FastAPI → handler → AWS), sem mockar camadas internas — atende ao requisito do README de integração com fluxo real.

---

## Observabilidade

### Logs (JSON estruturado)

Componentes emitem logs via `ApiLogger` / `ModelRunnerLogger` / `ModelTrainerLogger`:

```json
{
  "timestamp": "2026-07-29T22:22:32Z",
  "level": "INFO",
  "component": "main",
  "event": "recommendation_request_completed",
  "user_id": "u_0231",
  "latency_ms": 14.2,
  "cold_start_flag": false,
  "count": 10
}
```

Campos principais por request: `user_id`, `latency_ms`, `cold_start_flag`, `count`, `source`. Em ECS, logs vão para CloudWatch (`watchtower` quando disponível).

### Métricas (`GET /metrics`, Prometheus 0.0.4)

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `recommendations_api_requests_total` | Counter | Total de requests |
| `recommendations_api_errors_total` | Counter | Erros 4xx/5xx |
| `recommendations_api_cold_start_total` | Counter | Fallbacks cold start |
| `recommendations_api_latency_ms` | Summary | p50/p95 + sum/count |
| `recommendations_api_latency_avg_ms` | Gauge | Média |

Métricas mantidas in-memory no container (`InMemoryMetricsStore`), expostas via `prometheus_client` e **replicadas em logs estruturados** para consulta histórica no CloudWatch:

| Evento | Quando | Campos principais |
|--------|--------|-------------------|
| `api_request_metric` | Após cada request de recomendação | `latency_ms`, `is_error`, `is_cold_start`, `requests_total`, `errors_total`, `latency_p50_ms`, `latency_p95_ms` |
| `api_metrics_snapshot` | A cada `GET /metrics` | Totais agregados + p50/p95 |

Exemplo de query no CloudWatch Logs Insights:

```
fields @timestamp, requests_total, errors_total, latency_p50_ms, latency_p95_ms
| filter event = "api_metrics_snapshot"
| sort @timestamp desc
```

---

## O que faria diferente com mais tempo

1. **Inferência incremental** — scorear só pares novos/alterados em vez de cartesiano completo; ou cache Redis por `(user_id, product_id)`.
2. **Agendamento gerenciado** — EventBridge + ECS RunTask para `model_predict` diário, com alarmes se falhar.
3. **Blue/green no deploy da API** — CodeDeploy ou second ECS service antes de trocar tráfego.
4. **Versionamento de predições** — chave composta `(user_id, product_id, model_version)` no DynamoDB para rollback de modelo sem downtime.
5. **Endpoint de recomendação real-time opcional** — para usuários VIP ou A/B, com timeout e circuit breaker.
6. **Otimizar writes DynamoDB** — `batch_writer` com backoff, paralelismo e delete por GSI em vez de scan full table.
7. **Retreino automatizado** — pipeline que promove nova versão no Registry após métricas offline passarem.
8. **Documentação OpenAPI enriquecida** — exemplos de cold start, filtros e códigos de erro no Swagger.

---

## Observabilidade futura

| Hoje | Com mais tempo |
|------|----------------|
| Logs JSON em CloudWatch | Correlação com `trace_id` / OpenTelemetry |
| Métricas Prometheus in-memory + logs estruturados | Remote write → AMP/Grafana + dashboards |
| Latência p50/p95 no Summary | SLOs + alertas PagerDuty (p95 > X ms, error rate > Y%) |
| Contador de cold start | Dashboard de % cold start por cohort |
| — | Tracing distribuído (API → DynamoDB → S3) |
| — | Audit log de filtros aplicados (compliance) |
| — | Métricas de negócio: CTR estimado, diversidade de categorias |

---

## Estrutura do repositório

```
src/
├── model_train/           # treino + registro SageMaker
├── model_predict/         # batch scoring → S3 + DynamoDB
└── recommendations_api/ # FastAPI serving
docs/
└── architecture.jpeg      # diagrama de arquitetura AWS
tests/                     # unitários (espelham src/)
tests/integration/         # AWS real (3 testes)
terraform/                 # ECS, S3, DynamoDB, API Gateway, IAM, ECR, SageMaker
terraform/bootstrap/       # state S3 + DynamoDB lock (setup one-time)
docker/                    # Dockerfiles das 3 apps
.github/workflows/         # CI (unit) + CD (terraform → push → integração → train → predict)
data/                      # CSVs de referência local
model/                     # model.pkl + model_card.json originais do case
```

---

## Variáveis de ambiente principais

| Variável | App | Descrição |
|----------|-----|-----------|
| `DATA_BUCKET` | todos | Bucket S3 com `events.csv` / `products.csv` |
| `PREDICTIONS_DYNAMODB_TABLE` | predict, API | Tabela de predições |
| `MODEL_PACKAGE_GROUP_NAME` | train, predict | SageMaker Model Registry group |
| `INFERENCE_IMAGE_URI` | train | URI ECR registrada no model package |
| `BASELINE_MODEL_DIR` | train | Diretório com `model.pkl` do case (default `/app/model` no container) |
| `BASELINE_MODEL_PREFIX` | train | Prefixo S3 do artefato baseline seed (default `models/purchase_propensity/case-baseline-v1`) |
| `AWS_REGION` | todos | Região AWS (default `us-east-1`) |

Lista completa nos `load_config()` de cada `main.py` e nos outputs do Terraform (`terraform output`).

---

## Limitações conhecidas

- Predições desatualizadas entre execuções de `model_predict`.
- Replace DynamoDB O(n) — lento para catálogos grandes.
- Model package version hardcoded em `model_predict` (v1 — baseline do case; retreinos ficam no Registry mas não são servidos).
- Rollback do CI reverte **infra Terraform**, não dados escritos nos testes de integração.
- `scikit-learn` pinado em 1.8.x para compatibilidade com artefato existente no S3.

---

## Referências rápidas

- Model card: `model/model_card.json`
- Notebook de registro manual (legado): `notebooks/register_actual_model.ipynb` — substituído pelo seed automático em `model_train`
- Notebook de testes de endpoint: `notebooks/testing_endpoint.ipynb`
