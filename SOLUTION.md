# SOLUTION — Personalization Service

Documento de entrega do case técnico. Descreve o que foi construído, como executar, decisões tomadas e limitações conhecidas.

---

## Visão geral

A solução separa **treino**, **predição em batch**, **monitoramento de drift** e **serving HTTP** em quatro aplicações Python, todas containerizadas e deployadas na AWS via Terraform:

| Aplicação | Papel |
|-----------|--------|
| `model_train` | Treina o classificador sklearn, faz seed do `model.pkl` do case como v1 no Registry (se v1 ausente), publica artefato no S3 e registra a versão treinada como próxima |
| `model_predict` | Gera scores para todos os pares usuário×produto, grava snapshot no S3, substitui a tabela DynamoDB (usa sempre a versão do modelo que foi dada para o case) e dispara o drift monitor |
| `model_drift_monitor` | Avalia precision/recall e data drift sobre o snapshot de predições; persiste relatório no S3, notifica via SNS e pode disparar retreino (`model_train`) |
| `recommendations_api` | API REST síncrona que lê predições pré-computadas e responde em tempo de requisição |

**Por que batch + API leve?** O modelo scoreia ~30k pares (500 usuários × 60 produtos) por execução. Rodar feature engineering + inferência a cada `GET` aumentaria latência (centenas de ms a segundos) e custo. A API consulta DynamoDB (single-digit ms na leitura) e mantém o contrato síncrono exigido pelo case.

### Arquitetura na AWS

<p align="center">
  <img src="https://i.imgur.com/oiSi8dO.png" alt="Diagrama de arquitetura — Personalization Service na AWS" width="680" />
</p>

O fluxo completo, da esteira de CI/CD até a resposta síncrona ao usuário:

| Camada | Componentes | Responsabilidade |
|--------|-------------|------------------|
| **Code Versioning** | GitHub (repo + Actions CI/CD) | CI: `pytest` + `pylint`, tag de versão e build da imagem Docker. CD: `terraform apply`, push para ECR, testes de integração AWS e rollback se falhar |
| **Continuous Training** | ECS `model_train` | Executa o pipeline de treino; seed do modelo do case (v1) se o Registry estiver vazio; registra retreino como v2, v3…; disparado via `null_resource` após integração na CI |
| **Model Versioning** | SageMaker Model Registry + S3 (`models/`) | Versiona e aprova model packages; v1 = artefato original do case; demais versões = retreinos |
| **Data Dependency** | S3 (`training-data/`) | `events.csv` e `products.csv` — dependência compartilhada entre treino e predição |
| **Prediction** | ECS `model_predict` → S3 + DynamoDB | Batch: calcula scores, registra predições/features no S3 e grava último snapshot no DynamoDB; disparado via `null_resource` após train na CI; ao final, dispara `model_drift_monitor` (ECS RunTask) |
| **Drift monitoring** | ECS `model_drift_monitor` + SNS + S3 (`model-performance/`) | Precision/recall (ground truth = `purchase`), data drift (mediana 50%, PSI > 0.25, KS p < 0.05); relatório parquet versionado; e-mail SNS em drift/retreino; retreino via ECS RunTask de `model_train` se thresholds forem violados |
| **Endpoint (serving)** | API Gateway → VPC Link → **NLB → ALB** → **ECS Service** `recommendations_api` | Único cluster com serviço always-on; resposta **síncrona** lendo DynamoDB; cold start via `products.csv` no S3. **Sem Lambda** |
| **Monitoring (API)** | CloudWatch Logs + `/metrics` (in-memory) | Logs de infraestrutura e aplicação; métricas Prometheus/Datadog expostas pelo container da API |

### Clusters ECS: serviço (API) vs. jobs batch (ML)

Existem **quatro clusters ECS Fargate** independentes — um por aplicação — mas **dois modos de execução** distintos:

| Cluster | App | Modo | Comportamento |
|---------|-----|------|----------------|
| `personalization-recommendations-api` | `recommendations_api` | **ECS Service** (always-on) | `aws_ecs_service` com `desired_count` ≥ 1, registrado no **ALB**, health check no container, autoscaling opcional. Atende requisições HTTP síncronas 24/7 via API Gateway. |
| `personalization-model-train` | `model_train` | **RunTask** (one-shot) | Sem `ecs_service`. Cada execução é um task avulso (`aws ecs run-task`): treina, registra no SageMaker, encerra. |
| `personalization-model-predict` | `model_predict` | **RunTask** (one-shot) | Idem — gera predições, grava S3/DynamoDB, dispara drift monitor, encerra. |
| `personalization-model-drift-monitor` | `model_drift_monitor` | **RunTask** (one-shot) | Idem — avalia drift, grava relatório, pode disparar retreino, encerra. |

**Por que separar?** A API precisa de um **serviço long-lived** atrás do load balancer para latência previsível e disponibilidade contínua. Treino, predição e monitoramento são **pipelines batch**: sobem sob demanda, consomem recursos intensivos por minutos e terminam — não faz sentido mantê-los como serviço always-on. Os clusters batch também se encadeiam via `ecs:RunTask` (predict → drift → train) sem passar pela CI.

> Apenas o cluster **`recommendations-api`** possui ECS Service. Os demais existem só como “landing zone” para task definitions e RunTasks disparados pela CI, pelo Terraform (`null_resource`) ou por outro job (ex.: predict → drift).

### API Key (gerada no API Gateway)

A autenticação da API pública usa **API Keys nativas do Amazon API Gateway** — não há serviço de auth customizado nem validação de chave no FastAPI.

Fluxo de provisionamento (`terraform/api_gateway_recommendations.tf`):

1. **`aws_api_gateway_api_key`** — o Terraform cria a chave; a **AWS gera o valor** automaticamente.
2. **`aws_api_gateway_usage_plan`** — associa a chave ao stage `v1` da REST API.
3. **`aws_api_gateway_usage_plan_key`** — vincula key ↔ usage plan.
4. Cada método (exceto `GET /health`) declara **`api_key_required = true`** — o Gateway rejeita requests sem header `x-api-key` **antes** do tráfego chegar ao VPC Link/NLB.
5. O valor é **replicado** para **SSM Parameter Store** (`/personalization/recommendations-api/api-key`, SecureString) e exposto via `terraform output recommendations_api_key` — conveniência para testes, notebooks e CI; a **fonte da chave é o API Gateway**.

O container FastAPI **não lê nem valida** `RECOMMENDATIONS_API_KEY`; a env homônima no task definition da API existe por compatibilidade/legado, mas a proteção ocorre **somente na borda** (API Gateway).

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
     → model_predict dispara model_drift_monitor (ECS RunTask, fora da CI)
     → rollback Terraform (se integração falhar)
```

> O **drift monitor** não é um job separado na pipeline CD: ele é acionado automaticamente ao final de cada `model_predict` em produção (`DRIFT_MONITOR_ENABLED=true`). A CI também publica a imagem `model-drift-monitor` no ECR.

### Simplificações do case (vs. produção real)

Algumas escolhas deste repositório existem **apenas para facilitar a operação e a reprodução do case**. Em um ambiente Itaú/produção, a orquestração e a parametrização seriam diferentes:

| Tópico | Como está neste case | Como seria em produção |
|--------|----------------------|-------------------------|
| **Versão do modelo (`model_predict`)** | `HARDCODED_MODEL_PACKAGE_VERSION = 1` — sempre o baseline entregue no README | Parâmetro resolvido em runtime: versão (ou alias) **aprovada para produção** no SageMaker Model Registry |
| **Thresholds do drift monitor** | Constantes no código (ex.: precision/recall < 50%, score binário > 0.5, PSI/KS/mediana fixos em `DataDriftChecker` / `CallTrainPipeline`) | Parâmetros configuráveis — idealmente **metadados propagados pelo job de predição** (ou Parameter Store / feature store) por execução/modelo |
| **Disparo de `model_train` / `model_predict` na CI** | `null_resource` + `terraform apply -target=...` após testes de integração | **EventBridge** (agendamento ou eventos de dados) + **Step Functions** (ordenação, retries, aprovações humanas) no momento adequado do pipeline de ML |
| **Disparo do `model_drift_monitor`** | Recomendado via **`model_predict`** (RunTask com env dinâmica) | Mesmo padrão: predict conclui → dispara monitor; evitar RunTask “solto” sem o contexto da predição |

**1. Versão do modelo e thresholds hardcoded**

A versão **1** fixa em `model_predict` e os limiares fixos do drift monitor simplificam o case: o avaliador sempre vê o mesmo baseline e regras previsíveis. Em produção, **`model_predict` consultaria o Registry** (versão com status *Approved* / alias `Production`) e os **thresholds viriam de configuração externa** — por exemplo, metadados gravados junto com o snapshot de predições no S3 ou parâmetros versionados por modelo/campanha.

**2. Triggers na pipeline CI/CD**

Os jobs `trigger-model-train` e `trigger-model-predict` no GitHub Actions existem para **reproduzir o fluxo ponta a ponta após cada deploy**, sem exigir operação manual. Isso **não** modela o agendamento real de MLOps: em produção, treino e predição seriam acionados por **EventBridge** (cron, chegada de dados, alarmes) e orquestrados por **Step Functions**, desacoplados do deploy de infra/API.

**3. Dependência do drift monitor em relação ao `model_predict`**

O `model_drift_monitor` precisa, entre outras variáveis, de **`PREDICTIONS_S3_URI`** e **`PREDICTIONS_FILENAME`** — informações do snapshot que acabou de ser gerado. Esses valores são injetados pelo **`model_predict`** no `ecs:RunTask` (container overrides). A task definition estática do drift monitor traz apenas configuração de infra (buckets, SNS, cluster de retreino, etc.).

**Recomendação operacional:** sempre rode o **`model_predict`** e deixe que ele dispare o drift monitor (`DRIFT_MONITOR_ENABLED=true`). Disparar o drift monitor isoladamente (ex.: `terraform apply` com `run_model_drift_monitor_on_apply=true` ou `aws ecs run-task` manual) só funciona de forma limitada — há fallback para buscar a predição mais recente no S3, mas **sem o contexto completo** que o predict repassa no trigger.

---

## Como rodar o projeto

Há **três formas** de usar o repositório:

| Caminho | Quando usar | AWS necessária? |
|---------|-------------|-----------------|
| **A. Somente local** | Validar código, pytest, pylint | Não |
| **B. AWS manual** | Reproduzir o case em **outra conta/região** do zero | Sim |
| **C. GitHub Actions** | Deploy contínuo após push (como em produção do case) | Sim (secrets no repo) |

O passo a passo completo do caminho **B** está abaixo. Os caminhos A e C têm seções próprias mais adiante.

---

## Passo a passo — reproduzir o case em outro ambiente AWS

Guia para subir a stack completa (infra + imagens + batch + API pública) em uma **conta AWS nova** ou outra região, sem depender da CI.

### O que você terá ao final

- 4 imagens no **ECR**, 4 **clusters ECS** (1 service always-on + 3 jobs batch)
- **S3** (data + models), **DynamoDB** (predições), **SageMaker Model Registry**
- **API Gateway** público com **API Key** nativa
- Predições em produção após `model_predict`; drift monitor disparado automaticamente
- Logs em **CloudWatch**; alertas **SNS** (após confirmar subscription por e-mail)

Tempo estimado (primeira vez): **1–3 h** (inclui build de imagens e batch de ~30k linhas no DynamoDB).

**Checklist:**

| # | Etapa | Comando / seção |
|---|--------|-----------------|
| 1 | Pré-requisitos (Python, Docker, AWS CLI, Terraform) | §1 |
| 2 | Clone + `pytest` local | §2 |
| 3 | Bootstrap state (S3 + DynamoDB lock) | §3 |
| 4 | Configurar `terraform/versions.tf` backend | §4 |
| 5 | `terraform apply` (infra, sem batch) | §5 |
| 6 | Build + push 4 imagens → ECR | §6 |
| 7 | `model_train` → `model_predict` (drift automático) | §7 |
| 8 | Confirmar SNS + anotar API Key | §8 |
| 9 | `curl` / pytest / notebook | §9 |

---

### 1. Pré-requisitos

**Ferramentas na máquina:**

| Ferramenta | Versão mínima | Uso |
|------------|---------------|-----|
| Python | 3.12+ | Testes locais, scripts |
| Docker | recente | Build/push das imagens |
| AWS CLI v2 | — | Credenciais, ECR login, RunTask manual |
| Terraform | 1.5+ (CI usa 1.9.8) | Infra |

**Conta AWS — permissões IAM (resumo):** o usuário/role precisa criar e gerenciar, no mínimo: S3, DynamoDB, ECR, ECS, IAM roles, CloudWatch Logs, API Gateway, VPC Link, ELB (NLB/ALB), SageMaker Model Registry, SNS, SSM Parameter Store, e `ecs:RunTask` / `iam:PassRole` entre tasks.

**Credenciais:**

```bash
export AWS_REGION=us-east-1          # ou a região desejada
aws sts get-caller-identity            # confirme account id e acesso
```

---

### 2. Clone e ambiente Python

```bash
git clone <url-do-seu-repo>
cd itau_personalization_case          # ajuste o nome do diretório clonado

python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

**Validação rápida (sem AWS):**

```bash
pylint src
pytest -m "not integration"            # ~145 testes, ~2s
```

---

### 3. Bootstrap do state Terraform (uma vez por conta AWS)

O stack principal usa **backend remoto** (S3 + lock DynamoDB). Na **primeira** execução em uma conta, provisione o bootstrap:

```bash
cd terraform/bootstrap
terraform init
terraform apply -var="aws_region=${AWS_REGION}"
terraform output                          # anote bucket, tabela e backend_config
cd ../..
```

Isso cria:

- Bucket `personalization-terraform-state-<ACCOUNT_ID>`
- Tabela `personalization-terraform-locks`

---

### 4. Apontar o backend para sua conta

Edite `terraform/versions.tf` e substitua o bloco `backend "s3"` pelos valores do output do bootstrap (conta/região novas):

```hcl
backend "s3" {
  bucket         = "personalization-terraform-state-<SEU_ACCOUNT_ID>"
  key            = "terraform/state/model-train/terraform.tfstate"
  region         = "us-east-1"                    # mesma região do bootstrap
  dynamodb_table = "personalization-terraform-locks"
  encrypt        = true
}
```

Inicialize o stack principal:

```bash
cd terraform
terraform init -reconfigure
```

> Se migrar de local para remoto ou trocar bucket, use `terraform init -reconfigure`. Nunca commite state local com secrets.

---

### 5. Deploy da infraestrutura (sem rodar batch ainda)

Use uma **tag de imagem** consistente em todo o fluxo (ex.: `UAT` ou `local-dev`). O primeiro apply **não** deve disparar train/predict/drift — as imagens ainda não existem no ECR.

```bash
cd terraform
export IMAGE_TAG=UAT

terraform plan \
  -var="image_tag=${IMAGE_TAG}" \
  -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=false" \
  -var="run_model_predict_on_apply=false" \
  -var="run_model_drift_monitor_on_apply=false"

terraform apply \
  -var="image_tag=${IMAGE_TAG}" \
  -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=false" \
  -var="run_model_predict_on_apply=false" \
  -var="run_model_drift_monitor_on_apply=false"
```

**O que este apply cria:** ECR (4 repos), ECS clusters/task definitions, S3 (data + models + CSVs do case), DynamoDB, SageMaker model groups, API Gateway + API Key + VPC Link + NLB/ALB, SNS, IAM, CloudWatch, recursos de integração isolados.

**Opcional — e-mail de alertas de drift:**

```bash
terraform apply ... -var="drift_alert_email=seu@email.com"
```

Anote outputs úteis:

```bash
terraform output -raw data_bucket_name
terraform output -raw recommendations_api_gateway_endpoint
terraform output -raw recommendations_api_key
```

---

### 6. Build e push das imagens Docker → ECR

Login no ECR e defina o registry:

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"
```

Build e push das **4 imagens** (contexto = raiz do repo):

```bash
cd ..   # raiz do repositório

docker build -f docker/model_train/Dockerfile \
  --build-arg IMAGE_TAG="${IMAGE_TAG}" \
  -t "${ECR_REGISTRY}/personalization-model-train:${IMAGE_TAG}" .
docker push "${ECR_REGISTRY}/personalization-model-train:${IMAGE_TAG}"

docker build -f docker/model_predict/Dockerfile \
  -t "${ECR_REGISTRY}/personalization-model-predict:${IMAGE_TAG}" .
docker push "${ECR_REGISTRY}/personalization-model-predict:${IMAGE_TAG}"

docker build -f docker/model_drift_monitor/Dockerfile \
  -t "${ECR_REGISTRY}/personalization-model-drift-monitor:${IMAGE_TAG}" .
docker push "${ECR_REGISTRY}/personalization-model-drift-monitor:${IMAGE_TAG}"

docker build -f docker/recommendations_api/Dockerfile \
  -t "${ECR_REGISTRY}/personalization-recommendations-api:${IMAGE_TAG}" .
docker push "${ECR_REGISTRY}/personalization-recommendations-api:${IMAGE_TAG}"
```

**API recommendations (ECS Service):** após o push, force novo deployment para puxar a imagem:

```bash
aws ecs update-service \
  --cluster personalization-recommendations-api \
  --service personalization-recommendations-api \
  --force-new-deployment \
  --region "${AWS_REGION}"
```

Aguarde o service ficar estável e `/health` responder via API Gateway (pode levar alguns minutos).

---

### 7. Pipelines batch — ordem obrigatória

Ordem: **`model_train` → `model_predict` → (`model_drift_monitor` automático)**.

O drift monitor **não** deve ser o ponto de entrada — ele depende de `PREDICTIONS_S3_URI` / `PREDICTIONS_FILENAME` injetados pelo predict (ver [Simplificações do case — item 3](#simplificações-do-case-vs-produção-real)).

#### 7.1 Treino (seed baseline v1 + retreino)

```bash
cd terraform

terraform apply \
  -var="image_tag=${IMAGE_TAG}" \
  -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=true" \
  -var="run_model_predict_on_apply=false" \
  -var="run_model_drift_monitor_on_apply=false" \
  -target=null_resource.run_model_train_on_apply
```

Acompanhe logs: `/ecs/personalization/model-train`. Na primeira execução em Registry vazio, o job registra o `model.pkl` do case como **v1** e o retreino como **v2+**.

#### 7.2 Predição (S3 + DynamoDB + trigger drift)

```bash
sleep 10   # margem para o task de treino ser aceito (mesmo padrão da CI)

terraform apply \
  -var="image_tag=${IMAGE_TAG}" \
  -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=false" \
  -var="run_model_predict_on_apply=true" \
  -var="run_model_drift_monitor_on_apply=false" \
  -target=null_resource.run_model_predict_on_apply
```

Logs: `/ecs/personalization/model-predict`. Este job:

1. Grava `predictions_<timestamp>_<hash>.csv` no S3  
2. Substitui a tabela `personalization-predictions` no DynamoDB (~30k linhas, **vários minutos**)  
3. Dispara **`model_drift_monitor`** via `ecs:RunTask` com env dinâmica  

Logs do drift: `/ecs/personalization/model-drift-monitor`.

**Alternativa manual (equivalente aos outputs Terraform):**

```bash
eval "$(terraform output -raw model_train_ecs_run_task_command)"
eval "$(terraform output -raw model_predict_ecs_run_task_command)"
```

> **Não** rode `run_model_drift_monitor_on_apply=true` isoladamente, salvo para debug — prefira sempre o fluxo via predict.

---

### 8. Pós-deploy — SNS e API Key

**SNS:** após o primeiro apply, confirme a subscription no e-mail configurado em `drift_alert_email` (link “Confirm subscription”).

**API Key:** gerada nativamente no **API Gateway** (ver [API Key (gerada no API Gateway)](#api-key-gerada-no-api-gateway)). Obtenha o valor:

```bash
cd terraform
export API_KEY=$(terraform output -raw recommendations_api_key)
export ENDPOINT=$(terraform output -raw recommendations_api_gateway_endpoint)
```

---

### 9. Validar o deploy

**Health (público, sem key):**

```bash
curl -s "${ENDPOINT}/health"
```

**Recomendações (requer key):**

```bash
curl -s -H "x-api-key: ${API_KEY}" "${ENDPOINT}/recommendations/u_0231" | jq .
curl -s -H "x-api-key: ${API_KEY}" "${ENDPOINT}/recommendations/u_9999" | jq .   # cold start
curl -s -H "x-api-key: ${API_KEY}" "${ENDPOINT}/metrics" | head
```

**Testes automatizados (AWS real):**

```bash
cd ..   # raiz do repo
pytest tests/integration tests/api_tests -m integration -s
```

Ordem enforced: `model_train` → `model_predict` → API in-process → smoke/metrics via API Gateway.

> **Primeira execução dos `api_tests`:** exigem predições na tabela de **produção** (`personalization-predictions`). Complete o passo 7.2 antes.

Os testes de integração **não alteram recursos de produção** de forma destrutiva no Registry principal:
- `model_train` de integração usa `integration_model_package_group_name`
- `model_predict` e API in-process usam `integration_predictions_dynamodb_table_name`

#### Testes da API via notebook

Alternativa interativa ao `pytest tests/api_tests`:

```bash
cd notebooks
jupyter notebook testing_endpoint.ipynb
```

O notebook cobre requisições manuais + bateria automatizada (smoke, filtros, auth, cold start, métricas). URL e `x-api-key` vêm de `terraform output` / SSM, ou:

```bash
export RECOMMENDATIONS_API_BASE_URL="https://<api-id>.execute-api.${AWS_REGION}.amazonaws.com/v1"
export RECOMMENDATIONS_API_KEY="<sua-api-key>"
export RECOMMENDATIONS_TEST_USER_ID="u_0231"
export RECOMMENDATIONS_TEST_COLD_START_USER_ID="u_9999"
```

---

### 10. Re-deploys e atualizações de código

| Mudança | Ação |
|---------|------|
| Código Python (apps) | Rebuild + push imagem afetada → `ecs update-service` (API) ou novo RunTask (batch) |
| Só Terraform (infra) | `terraform apply` com mesmas vars; `run_model_*_on_apply=false` na maioria dos casos |
| Nova tag de release | Aplique com `-var="image_tag=<nova>"`, repita push ECR e batch se necessário |
| Destruir stack | `terraform destroy` (cuidado: buckets com `force_destroy` apagam dados) |

---

### 11. Caminho alternativo — GitHub Actions (CI/CD)

Se preferir não executar os passos 5–7 manualmente:

1. Configure secrets no repositório: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
2. Bootstrap + backend configurados (passos 3–4) **antes** do primeiro push de CD
3. Push na branch → workflow **Personalization CI/CD** executa: terraform → push ECR → integração → train → predict

Detalhes: [Pipeline CI/CD](#pipeline-cicd-github-actions).

---

### 12. Desenvolvimento local apontando para AWS

Com infra já aplicada, é possível rodar apps na máquina usando recursos remotos:

**API local:**

```bash
export AWS_REGION=us-east-1
export DATA_BUCKET=$(terraform -chdir=terraform output -raw data_bucket_name)
export PREDICTIONS_DYNAMODB_TABLE=$(terraform -chdir=terraform output -raw predictions_dynamodb_table_name)

PYTHONPATH=src uvicorn recommendations_api.main:app --host 0.0.0.0 --port 8000
```

**Pipelines batch locais** (mesmas env vars dos containers — ver outputs Terraform):

```bash
export DATA_BUCKET=... MODEL_BUCKET=... MODEL_PACKAGE_GROUP_NAME=...
export INFERENCE_IMAGE_URI=... IMAGE_TAG=local-dev
PYTHONPATH=src python -m model_train.main

export PREDICTIONS_DYNAMODB_TABLE=...
PYTHONPATH=src python -m model_predict.main
```

> Rodar `model_predict` localmente **não** dispara o drift monitor no ECS, a menos que `DRIFT_MONITOR_*` estejam configurados e `DRIFT_MONITOR_ENABLED=true`.

---

### 13. Troubleshooting comum

| Sintoma | Causa provável | O que fazer |
|---------|----------------|-------------|
| ECS task `CannotPullContainerError` | Imagem não existe no ECR para `image_tag` | Repita passo 6 com a mesma tag do Terraform |
| API 403 sem key / 502 | Service ainda subindo ou API Key errada | Aguarde ECS service; use `terraform output recommendations_api_key` |
| `api_tests` com `count=0` | DynamoDB de produção vazio | Rode passo 7.2 (`model_predict`) |
| Drift monitor: `PREDICTIONS_S3_URI is required` | RunTask sem overrides do predict | Rode predict (passo 7.2); não dispare drift isolado |
| SageMaker seed falha | Registry já tem v1 ou imagem train ausente no ECR | Verifique ECR e logs do train |
| SNS sem e-mail | Subscription não confirmada | Confirme link no e-mail (passo 8) |

---

### Referência rápida — comandos úteis

```bash
# Outputs
terraform -chdir=terraform output

# Logs (exemplos)
aws logs tail /ecs/personalization/model-predict --follow --region "${AWS_REGION}"
aws logs tail /ecs/personalization/recommendations-api --follow --region "${AWS_REGION}"

# Docker local (sem push)
docker build -f docker/recommendations_api/Dockerfile -t recommendations-api .
docker build -f docker/model_predict/Dockerfile -t model-predict .
docker build -f docker/model_train/Dockerfile --build-arg IMAGE_TAG=local-dev -t model-train .
docker build -f docker/model_drift_monitor/Dockerfile -t model-drift-monitor .
```

---

## Pipeline CI/CD (GitHub Actions)

A esteira está em `.github/workflows/` e é orquestrada por `workflow.yaml` (**Personalization CI/CD**).

### Gatilhos

| Evento | CI (lint + testes) | CD (deploy AWS) |
|--------|-------------------|-----------------|
| `pull_request` | ✅ | ❌ |
| `push` (qualquer branch) | ✅ | ✅ |
| `workflow_dispatch` | ✅ | ✅ |

### Visão geral dos workflows

| Arquivo | Papel |
|---------|--------|
| `workflow.yaml` | Orquestrador principal — encadeia CI → tag → CD |
| `pylint_and_pytest.yaml` | `pylint src` + `pytest -m "not integration"` |
| `cicd_general.yaml` | Resolve `image_tag` e cria git tag em `main` |
| `terraform_docker.yaml` | Terraform apply, push ECR, integração, train, predict, rollback |
| `integration_tests.yaml` | `pytest tests/integration tests/api_tests -m integration` (timeout 90 min) |

### Fluxo completo (push)

```
workflow.yaml
  │
  ├─ 1. ci-quality ────────────── pylint + pytest unitário (~145 testes)
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
          ├─ push-model-drift-monitor-image ─┤
          └─ push-recommendations-api-image ─┘
          │
          ├─ integration-tests ────────── pipelines isolados + API Gateway
          │     • order 1–3: model_train → model_predict → API in-process
          │     • order 4–5: smoke e metrics via API Gateway público
          │     (recursos de integração isolados; api_tests leem tabela DynamoDB de **produção**)
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

**Batch jobs só após integração.** `model_train` e `model_predict` em produção só disparam se os testes de integração **e** os testes de API (`tests/api_tests`) passarem. Falha em qualquer um deles aciona o rollback do state Terraform. O treino roda primeiro; aguarda-se **10 segundos** (`sleep 10`) antes do predict, dando margem para o ECS RunTask de treino ser aceito pela API (o job não espera o treino terminar — apenas evita disparo simultâneo).

> **Nota (case vs. produção):** esse encadeamento train → predict via Terraform na CD é uma **simplificação para reproduzir o case** após deploy. Em produção real, treino e predição seriam disparados por **EventBridge** e **Step Functions**, no timing correto do pipeline de dados/ML — não acoplados ao `terraform apply`. Ver [Simplificações do case](#simplificações-do-case-vs-produção-real).

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

Em `main`, também publica `:latest` nos quatro repositórios ECR (`push_latest: true`).

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
| `ecr.tf` | 4 repositórios ECR + lifecycle (mantém 10 imagens) |
| `iam.tf` | Roles ECS task/execution — S3, DynamoDB, SageMaker, ECS RunTask, SNS, logs |
| `cloudwatch.tf` | Log groups por serviço |
| `sagemaker_model_registry.tf` | Model groups produção + integração |
| `ecs_model_train.tf` | Cluster + task definition + `null_resource` RunTask |
| `ecs_model_predict.tf` | Cluster + task definition + `null_resource` RunTask |
| `ecs_model_drift_monitor.tf` | Cluster + task definition + `null_resource` RunTask |
| `ecs_recommendations_api.tf` | ALB interno, NLB, ECS service, autoscaling |
| `sns.tf` | Tópico SNS + subscription e-mail para alertas de drift |
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
                    └──────────────▲──────────┬─────────┘
                                   │ lê       │ RunTask (pós-predict)
                    ┌──────────────┴──┐   ┌───▼──────────────────────────┐
                    │ SageMaker       │   │ ECS — model_drift_monitor    │
                    │ Model Registry  │   │ S3 model-performance/ + SNS  │
                    └──────────────▲──┘   └───┬──────────────────────────┘
                                   │ registra │ RunTask (se drift)
                    ┌──────────────┴──────────▼──────────────────────────┐
                    │   ECS Fargate — model_train                        │
                    └────────────────────────────────────────────────────┘

        S3 data bucket ◄── events.csv, products.csv, predictions/, model-performance/
        S3 models bucket ◄── model.tar.gz, artefatos de treino
        SNS ◄── alertas de data drift e retreino
        ECR ◄── 4 imagens Docker (tag = var.image_tag)
```

### Variáveis principais

| Variável | Obrigatória | Default | Efeito |
|----------|-------------|---------|--------|
| `image_tag` | **sim** | — | Tag Docker em ECR e task definitions |
| `aws_region` | não | `us-east-1` | Região de deploy |
| `project_name` | não | `personalization` | Prefixo de nomes de recursos |
| `run_model_train_on_apply` | não | `true` | Se `true`, `null_resource` dispara ECS RunTask de treino no apply |
| `run_model_predict_on_apply` | não | `true` | Se `true`, `null_resource` dispara ECS RunTask de predict no apply |
| `run_model_drift_monitor_on_apply` | não | `true` | Se `true`, `null_resource` dispara ECS RunTask de drift monitor no apply |
| `drift_alert_email` | não | `eugeniovalcilio@gmail.com` | E-mail inscrito no SNS de alertas de drift |
| `monitoring_prefix` | não | `model-performance` | Prefixo S3 dos relatórios do drift monitor |
| `training_data_prefix` | não | `training-data` | Prefixo S3 dos CSVs |
| `predictions_prefix` | não | `predictions` | Prefixo S3 das predições |
| `ecs_task_cpu` / `memory` | não | 4096 / 8192 | Batch train/predict/drift |
| `model_package_group_name` | não | `purchase-propensity-model-group` | Registry produção |

Na CI, o apply inicial usa `run_model_*_on_apply=false` (train, predict e drift monitor). Após integração: job `trigger-model-train` (apply targeted com train=true), depois `trigger-model-predict` (sleep 10s + apply targeted com predict=true). O drift monitor roda em produção **após** cada predict bem-sucedido, não como job separado na CD.

### Recursos de integração (isolados)

Para não poluir produção durante os testes de integração:

| Recurso produção | Recurso de integração | Output Terraform |
|------------------|----------------------|------------------|
| `personalization-predictions` (DynamoDB) | `personalization-integration-predictions` | `integration_predictions_dynamodb_table_name` |
| `purchase-propensity-model-group` (SageMaker) | `personalization-integration-model-group` | `integration_model_package_group_name` |

Os testes em `tests/helpers/aws_integration.py` leem esses outputs e apontam `model_train` / `model_predict` / API para os recursos de integração.

### `null_resource.run_model_train_on_apply`, `run_model_predict_on_apply` e `run_model_drift_monitor_on_apply`

Cada um dispara um **ECS RunTask** one-shot via `local-exec` + AWS CLI quando a variável correspondente é `true`.

| Recurso | Serviço | Quando na CI |
|---------|---------|--------------|
| `null_resource.run_model_train_on_apply` | `model_train` | Job `trigger-model-train`, após integração |
| `null_resource.run_model_predict_on_apply` | `model_predict` | Job `trigger-model-predict`, após train + `sleep 10` |
| `null_resource.run_model_drift_monitor_on_apply` | `model_drift_monitor` | Apenas apply manual (`-target=...`); **não recomendado** — em operação normal é disparado por `model_predict` |

Comportamento comum:

- **Triggers:** `task_definition_arn` + `image_tag` — reexecuta se a task definition ou tag mudarem.
- **CI:** apply `-target=null_resource.*` com a flag daquele job em `true` e a outra em `false`.
- **Apply local padrão:** ambas com `default = true` — cuidado ao rodar `terraform apply` manualmente.

Comandos equivalentes manuais:

```bash
terraform output -raw model_train_ecs_run_task_command
terraform output -raw model_predict_ecs_run_task_command
terraform output -raw model_drift_monitor_ecs_run_task_command
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
terraform output -raw model_drift_monitor_image_uri
terraform output -raw recommendations_api_image_uri

# Drift monitor
terraform output -raw model_drift_monitor_ecs_cluster_name
terraform output -raw model_drift_sns_topic_arn
terraform output -raw monitoring_prefix
```

### Apply manual (fora da CI)

> **Guia completo:** o passo a passo detalhado (bootstrap, ECR, ordem train → predict, validação e troubleshooting) está em [Passo a passo — reproduzir o case em outro ambiente AWS](#passo-a-passo--reproduzir-o-case-em-outro-ambiente-aws).

Resumo dos comandos Terraform para batch (após infra + imagens no ECR):

```bash
cd terraform
export IMAGE_TAG=UAT AWS_REGION=us-east-1

terraform apply -var="image_tag=${IMAGE_TAG}" -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=true" -var="run_model_predict_on_apply=false" \
  -var="run_model_drift_monitor_on_apply=false" \
  -target=null_resource.run_model_train_on_apply

sleep 10

terraform apply -var="image_tag=${IMAGE_TAG}" -var="aws_region=${AWS_REGION}" \
  -var="run_model_train_on_apply=false" -var="run_model_predict_on_apply=true" \
  -var="run_model_drift_monitor_on_apply=false" \
  -target=null_resource.run_model_predict_on_apply
```

Os CSVs `events.csv` e `products.csv` são enviados ao S3 pelo próprio Terraform (diretório `data/`).

### IAM (resumo)

A role `ecs_task` compartilhada pelos quatro serviços permite:

- **S3** — leitura/escrita nos buckets `data` e `models`; leitura de predições e escrita de relatórios de monitoramento
- **DynamoDB** — CRUD nas tabelas produção e integração
- **SageMaker** — criar/describe model packages e groups
- **ECS** — `RunTask` entre clusters (predict → drift monitor; drift monitor → train)
- **SNS** — publicar alertas de drift/retreino
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
    {"product_id": "p_0042", "score": 0.67}
  ]
}
```

**Validação:** `user_id` deve seguir o padrão `u_XXXX` (regex `^u_\d{4}$`); IDs inválidos retornam HTTP 400.

### `POST /recommendations_filtered`

Body JSON com filtros opcionais: `limit`, `exclude_product_ids`, `category`, `categories`, `exclude_categories`, `min_price`, `max_price`, `min_avg_rating`, `min_popularity_score`, `min_recommendation_score`, `only_affinity_match`, `exclude_cold_start`.

Categorias aceitas: `beleza`, `casa`, `eletronicos`, `esporte`, `livros`, `moda`. Product IDs seguem `p_XXX` (`^p_\d{3}$`).

Resposta inclui metadados enriquecidos (`category`, `price`, `interactions`, `user_affinity_match`, etc.) além do score. Quando a linha no DynamoDB não traz `category`, a API enriquece via join com `products.csv` (S3).

### Autenticação

Resumo: header **`x-api-key`**, validado **apenas no API Gateway** (ver [API Key (gerada no API Gateway)](#api-key-gerada-no-api-gateway)). Rotas protegidas retornam 403 sem chave; `/health` é público (`api_key_required = false`).

Para obter a chave após deploy:

```bash
terraform output -raw recommendations_api_key
# ou, via SSM:
aws ssm get-parameter --name "$(terraform output -raw recommendations_api_key_ssm_parameter)" --with-decryption
```

O FastAPI **não implementa** middleware de API key — quem bloqueia é o Gateway antes do VPC Link.

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

> **Treino vs predição:** no `model_predict`, o universo de pares é o **produto cartesiano** usuários×produtos (~30k linhas). No `model_train`, o dataset supervisionado usa apenas pares `(user_id, product_id)` que **já aparecem** em `events.csv` — ver [Target de treino](#target-de-treino-model_train).

---

## Target de treino (`model_train`)

O retreino em `model_train` aprende **propensão de compra**: para cada par usuário–produto com histórico, o modelo estima a probabilidade de que houve (ou haveria) uma **compra** naquele par.

Implementação em `src/model_train/domain/gateways/modelhandler.py` (`build_training_dataset()` + `_build_labels()`).

### Definição da target (label)

| Valor | Significado |
|-------|-------------|
| **`1`** | Existe pelo menos um evento `event_type == "purchase"` para `(user_id, product_id)` |
| **`0`** | O par aparece em `events.csv` (view, click, add_to_cart, etc.), mas **sem** `purchase` |

Eventos que **não** são `purchase` entram nas **features** (ex.: `interactions` conta todos os eventos do par), mas **não** definem label positiva.

### Universo de exemplos

1. Extrair pares únicos: `events[["user_id", "product_id"]].drop_duplicates()`.
2. Derivar features com `_build_features()` (mesma lógica de `interactions`, `price`, `user_affinity_match`, etc.).
3. Derivar labels com `_build_labels()`: merge left com pares que tiveram `purchase`; `fillna(0)`.

Pares usuário–produto **sem nenhuma interação** no CSV **não** entram no treino (diferente do batch de inferência, que scoreia o cartesiano completo).

### Treino e métricas offline

`ModelTrainer.train()` (`src/model_train/domain/usecases/modeltrainer.py`):

- Valida features via entidade `Customer`.
- Split **80/20** estratificado (`stratify=labels`, `random_state=42`).
- `StandardScaler` + `LogisticRegression(max_iter=1000)`.
- Métricas no hold-out: **accuracy** e **ROC-AUC** (probabilidade da classe positiva = compra).

A saída do modelo treinado é a mesma do case: **probabilidade de compra** entre 0 e 1, usada downstream como `recommendation_score`.

### Alinhamento com o case

O `model/model_card.json` descreve propensão de compra e observa que pequenas variações de critério (ex.: ponderar recência, usar só purchases na afinidade) seriam aceitáveis se documentadas. **Escolha adotada:** label binária estrita — **`purchase` = 1**, demais interações do mesmo par = **0**, sobre pares que já existem no histórico de eventos.

---

## SageMaker Model Registry e seed do modelo baseline

O README do case entrega um **`model/model.pkl` já treinado** e deixa explícito que o foco não é retreinar ou melhorar o modelo. Mesmo assim, o pipeline `model_train` existe para demonstrar continuous training. Para conciliar os dois mundos, o treino **bootstrapa o Registry** com o artefato original antes de registrar qualquer retreino.

### Fluxo por execução

```
model_train.run_training_pipeline()
  │
  ├─ 1. has_model_package_version(group, 1)?
  │      └─ NÃO (v1 ausente)
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
| Checagem de versões existentes | `src/model_train/domain/gateways/awsconnector.py` → `has_model_package_version(..., 1)` |
| Upload + registro | `upload_model_directory()` + `register_model_package()` (reutilizados pelo fluxo normal) |

### Artefato baseline e container

- Diretório esperado: `model/model.pkl` e, opcionalmente, `model/model_card.json`.
- A imagem Docker de treino copia `model/` para `/app/model` e define `BASELINE_MODEL_DIR=/app/model`.
- O artefato baseline sobe para S3 em `BASELINE_MODEL_PREFIX` (default `models/purchase_propensity/case-baseline-v1`), separado do prefixo versionado por `IMAGE_TAG` usado no retreino.

### Relação com `model_predict`

`model_predict` continua consumindo **`HARDCODED_MODEL_PACKAGE_VERSION = 1`** — ou seja, sempre o pacote baseline do case em produção, alinhado ao requisito do README. As versões 2+ ficam disponíveis no Registry para auditoria, comparação offline ou futura promoção de modelo, mas **não entram no serving** neste case.

> **Case vs. produção:** a versão fixa é **deliberada para simplificar o case**. Em produção, `model_predict` resolveria a versão (ou alias) **em produção no SageMaker Model Registry**, não um inteiro hardcoded no código. Ver [Simplificações do case](#simplificações-do-case-vs-produção-real).

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

- O Model Package Group **já possui** a versão **1** (`has_model_package_version` → true).
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

## Model drift monitor (`model_drift_monitor`)

Quarto app batch, acionado automaticamente ao final de cada `model_predict` em produção (via `ecs:RunTask`). Nos testes de integração, o disparo fica desabilitado (`DRIFT_MONITOR_ENABLED=false`).

> **Forma recomendada de execução:** rode sempre o **`model_predict`** e deixe-o disparar o drift monitor. Variáveis críticas (`PREDICTIONS_S3_URI`, `PREDICTIONS_FILENAME`) são definidas **no momento do RunTask** pelo predict; a task definition sozinha não contém o snapshot a avaliar. Ver [Simplificações do case — item 3](#simplificações-do-case-vs-produção-real).

### Fluxo

```
model_predict conclui
  → upload predictions_<timestamp>_<hash>.csv no S3
  → replace DynamoDB
  → trigger_drift_monitor_task(PREDICTIONS_S3_URI, PREDICTIONS_FILENAME)
       │
       ├─ baixa events.csv / products.csv + CSV de predições
       ├─ monta frame de avaliação (pares com histórico em events)
       ├─ precision / recall
       │     • ground truth: actual_purchase = 1 se houve event_type == "purchase"
       │     • predição binária: recommendation_score > 0.5
       ├─ data drift por feature do modelo
       │     • mediana relativa > 50%
       │     • PSI > 0.25
       │     • KS p-value < 0.05
       ├─ grava model_performance_<hash>_<timestamp>.parquet em s3://<bucket>/model-performance/
       ├─ SNS (se data drift): alerta com detalhes por feature
       └─ se precision < 50% OU recall < 50% OU data drift
             → ECS RunTask de model_train (retreino)
             → SNS adicional informando retreino
```

### Onde está o código

| Peça | Arquivo |
|------|---------|
| Entrypoint | `src/model_drift_monitor/main.py` |
| Orquestração | `domain/gateways/metricshandler.py` |
| Precision / recall | `domain/usecases/precisioncalculator.py`, `recallcalculator.py` |
| Data drift | `domain/usecases/datadriftchecker.py` |
| Disparo de retreino | `domain/usecases/calltrainpipeline.py` |
| AWS (S3, SNS, ECS) | `domain/gateways/awsconnector.py` |
| Trigger pós-predict | `src/model_predict/main.py` + `model_predict/domain/gateways/awsconnector.py` |

### Infra

- ECS cluster/task `personalization-model-drift-monitor`
- Tópico SNS `personalization-model-drift-alerts` + subscription e-mail (`var.drift_alert_email`)
- Relatórios em `s3://<data_bucket>/model-performance/`
- IAM: `ecs:RunTask` com wildcard de revisão (`task-definition/*:*`) + `iam:PassRole` + `sns:Publish`

> **Escopo do case:** o retreino registra novas versões no SageMaker, mas o `model_predict` continua servindo **v1** (baseline). O monitor demonstra o loop de MLOps; promoção automática de modelo servido ficaria para uma evolução futura.

> **Thresholds hardcoded:** precision/recall < 50%, limiar de score 0.5, PSI/KS/mediana em `DataDriftChecker` estão **fixos no código** para simplificar o case. Em produção, seriam **parâmetros** — preferencialmente metadados associados à execução de predição (propagados pelo `model_predict`), não constantes em Python. Ver [Simplificações do case — item 1](#simplificações-do-case-vs-produção-real).

---

## Decisões de arquitetura e trade-offs

### 1. Batch predict + DynamoDB em vez de inferência online

| Prós | Contras |
|------|---------|
| Latência baixa e previsível na API | Predições ficam stale até próximo batch |
| Custo de inferência concentrado em job agendado | Novos usuários/produtos só aparecem após re-run |
| Escala horizontal da API sem carregar sklearn | Tabela grande (~30k+ itens) no replace completo |

O replace completo do DynamoDB é aceitável neste case (dados estáticos). Em produção, predições e writes deveriam ser incrementais.

### 2. Quatro apps separadas

Isola responsabilidades e permite escalar/versionar treino, batch, monitoramento e API independentemente. Custo: mais imagens Docker, mais Terraform e mais superfície operacional.

### 3. Clean Architecture

Cada app segue `domain/entities`, `domain/usecases`, `domain/gateways`, `main.py`. Isso separa regras de negócio de integrações externas e facilita testes unitários (mocks nos gateways) e de integração (AWS real nas bordas).

### 4. SageMaker Model Registry

Resumo: seed automático do `model.pkl` do case como **v1** quando o Registry está vazio; retreinos entram como **v2+**. Detalhes completos na seção [SageMaker Model Registry e seed do modelo baseline](#sagemaker-model-registry-e-seed-do-modelo-baseline).

`model_predict` consome **versão fixa 1** (`HARDCODED_MODEL_PACKAGE_VERSION = 1`): simplificação do case (ver [Simplificações do case](#simplificações-do-case-vs-produção-real)). Em produção real, a versão servida viria do **Model Registry** (pacote aprovado / alias de produção).

### 5. Métricas in-memory + logs estruturados

Contadores e latências ficam in-memory e alimentam `/metrics` via `prometheus_client`. Cada request emite `api_request_metric`; cada scrape de `/metrics` emite `api_metrics_snapshot` — ambos recuperáveis no CloudWatch Logs Insights.

### 6. CI/CD com gate de integração

Testes AWS rodam **após** `terraform apply` e **push das imagens** para o ECR; `model_train` e `model_predict` em produção só disparam se integração **e** API tests passarem (train → sleep 10s → predict). Falha em qualquer teste → rollback do state Terraform. Ver [Pipeline CI/CD](#pipeline-cicd-github-actions) e [Infraestrutura Terraform](#infraestrutura-terraform).

### 7. API síncrona (e caminho assíncrono futuro)

O case exige resposta síncrona; a arquitetura prioriza latência baixa na leitura — batch de inferência + DynamoDB é uma das alavancas principais.

Em escala Itaú, se a inferência passasse a ocorrer em tempo de request, faria sentido evoluir para uma **API assíncrona**:

- **Resposta imediata** com `request_id`, sem bloquear até o fim da inferência; o cliente consulta o resultado depois.
- **Fila FIFO** absorve picos, serializa processamento e simplifica retries em falhas transientes.
- **Backpressure explícito** — limitar concorrência na fila torna o scaling mais previsível sob carga máxima.

---

## Testes

### Unitários (`tests/`, espelha `src/`)

- **145 testes** cobrindo feature engineering, handlers, filtros, cold start, métricas, drift monitor (precision/recall/data drift), gateways, seed do modelo baseline e helpers de API Gateway (mocks boto3/sklearn).
- Execução rápida (~2s), roda em todo PR.
- Helpers reutilizáveis em `tests/helpers/`:
  - `aws_integration.py` — leitura de outputs Terraform, builders de env, checks S3/DynamoDB
  - `api_gateway.py` — cliente HTTP, parsing Prometheus/Datadog, resolução de API key via SSM
  - `recommendations_fixtures.py` — `FakeAwsConnector` e dados de exemplo para unitários
  - `test_api_gateway.py` — testes unitários dos helpers acima

### Integração (`tests/integration/` + `tests/api_tests/`)

Pipeline **sem mocks**, contra AWS real:

| Ordem | Suite | Valida |
|-------|-------|--------|
| 1 | `model_train` | Pipeline de treino → seed baseline (se Registry vazio) → S3 + SageMaker Registry (grupo de integração) |
| 2 | `model_predict` | Pipeline completo → S3 + DynamoDB (tabela de integração) |
| 3 | `recommendations_api` | `TestClient` + conectores reais (tabela DynamoDB de integração, S3, métricas) |
| 4 | `api_tests/test_smoke.py` | Smoke tests HTTP via API Gateway (`/health`, recomendações, filtros, auth) |
| 5 | `api_tests/test_metrics.py` | `/metrics` Prometheus + Datadog (`?format=datadog`) + `?format=both` + formato inválido (400) |

Testes unitários adicionais em `tests/model_drift_monitor/` cobrem precision, recall, data drift (PSI/KS/mediana), persistência S3 e trigger de retreino (mocks).

Testes de **carga** ficam em `notebooks/api_load_test.ipynb` — duas sessões comparáveis (usuários de `events.csv` vs cold start), 4×5 requisições concorrentes cada, compara latências client-side e coleta `/metrics` Prometheus ao final. Execução manual, fora da pipeline CI.

Para validar a API de forma interativa (sem `pytest`), use `notebooks/testing_endpoint.ipynb` — ver [Testes da API via notebook](#testes-da-api-via-notebook) no passo 9 do guia de reprodução.

Os testes em `tests/api_tests` replicam essas validações na pipeline CI. Falha em qualquer etapa bloqueia os batch jobs de produção e aciona rollback do state Terraform na pipeline CD.

O teste in-process da API exercita HTTP de ponta a ponta (`TestClient` → FastAPI → handler → AWS), sem mockar camadas internas — atende ao requisito do README de integração com fluxo real.

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

### Métricas (`GET /metrics`)

**Prometheus (default)** — `GET /metrics` ou `GET /metrics?format=prometheus`

Content-Type: `text/plain; version=0.0.4`

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `recommendations_api_requests_total` | Counter | Total de requests |
| `recommendations_api_errors_total` | Counter | Erros 4xx/5xx |
| `recommendations_api_cold_start_total` | Counter | Fallbacks cold start |
| `recommendations_api_latency_ms` | Summary | p50/p95 + sum/count |
| `recommendations_api_latency_avg_ms` | Gauge | Média |

**Datadog (Metrics API v2)** — `GET /metrics?format=datadog`

Retorna JSON no formato `series` aceito pelo endpoint [`POST /api/v2/series`](https://docs.datadoghq.com/api/latest/metrics/#submit-metrics), pronto para ingestão por agente, sidecar ou pipeline de observabilidade:

```bash
curl -H "x-api-key: $API_KEY" "$ENDPOINT/metrics?format=datadog"
```

| Métrica Datadog | Tipo (v2) | Descrição |
|-----------------|-----------|-----------|
| `recommendations_api.requests.total` | count (1) | Total de requests |
| `recommendations_api.errors.total` | count (1) | Erros 4xx/5xx |
| `recommendations_api.cold_start.total` | count (1) | Fallbacks cold start |
| `recommendations_api.latency.count` | gauge (3) | Observações de latência |
| `recommendations_api.latency.sum_ms` | gauge (3) | Soma das latências (ms) |
| `recommendations_api.latency.avg_ms` | gauge (3) | Média (ms) |
| `recommendations_api.latency.p50_ms` | gauge (3) | Percentil 50 (ms) |
| `recommendations_api.latency.p95_ms` | gauge (3) | Percentil 95 (ms) |

Todas as séries incluem a tag `service:recommendations_api`.

**Ambos** — `GET /metrics?format=both` retorna JSON com `prometheus` (texto) e `datadog` (`series`).

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
2. **Agendamento gerenciado** — EventBridge + Step Functions para `model_predict` e `model_train` (substituindo triggers acoplados ao deploy na CI; ver [Simplificações do case](#simplificações-do-case-vs-produção-real)).
3. **Blue/green no deploy da API** — CodeDeploy ou second ECS service antes de trocar tráfego.
4. **Versionamento de predições** — chave composta `(user_id, product_id, model_version)` no DynamoDB para rollback de modelo sem downtime.
5. **Endpoint de recomendação real-time opcional** — para usuários VIP ou A/B, com timeout e circuit breaker.
6. **Otimizar writes DynamoDB** — `batch_writer` com backoff, paralelismo e delete por GSI em vez de scan full table.
7. **Retreino automatizado com promoção** — o loop drift → train já existe; falta política de promoção da versão servida no Registry após métricas offline.
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

## Notebooks

Exploração e validação manual — **fora da pipeline CI**:

| Notebook | Propósito |
|----------|-----------|
| `notebooks/testing_endpoint.ipynb` | **Série de testes da API** via API Gateway: (1) requisições manuais por endpoint; (2) bateria automatizada espelhando `tests/api_tests/` + casos de borda. Resolve URL/chave via Terraform/SSM |
| `notebooks/api_load_test.ipynb` | Teste de carga: 2 sessões (known vs cold start), 4 rounds × 5 req concorrentes, compara latências + `/metrics` |
| `notebooks/features_explorations.ipynb` | EDA sobre `events.csv` e `products.csv` |
| `notebooks/generating_input_dataset.ipynb` | Validação da geração do dataset de features vs expectativas do modelo |
| `notebooks/model_understanding.ipynb` | Inspeção do `model.pkl` bundled (coeficientes, scaler, feature cols) |
| `notebooks/register_actual_model.ipynb` | **Legado** — registro manual no SageMaker; substituído pelo seed automático em `model_train` |

O diagrama de arquitetura AWS está no topo deste documento (Imgur); não há arquivo local em `docs/`.

---

## Estrutura do repositório

```
src/
├── model_train/             # treino + registro SageMaker
├── model_predict/           # batch scoring → S3 + DynamoDB + trigger drift
├── model_drift_monitor/     # precision/recall/data drift → S3 + SNS + retreino
└── recommendations_api/     # FastAPI serving (porta 8000)
tests/                       # unitários (espelham src/)
tests/helpers/               # fixtures e helpers compartilhados (AWS + API Gateway)
tests/integration/           # pipelines AWS isolados (3 testes ordenados)
tests/api_tests/             # smoke + metrics via API Gateway público
tests/model_drift_monitor/   # unitários do drift monitor
notebooks/                   # exploração, carga e testes manuais (6 notebooks)
terraform/                   # ECS Fargate, S3, DynamoDB, SNS, API Gateway, IAM, ECR, SageMaker
terraform/bootstrap/         # state S3 + DynamoDB lock (setup one-time)
docker/                      # Dockerfiles das 4 apps
.github/workflows/           # CI (unit) + CD (terraform → push → integração → train → predict)
data/                        # CSVs de referência local (~500 usuários, 60 produtos)
model/                       # model.pkl, model.tar.gz e model_card.json originais do case
PLAN.md                      # planejamento interno de arquitetura (pré-implementação)
```

---

## Variáveis de ambiente principais

| Variável | App | Descrição |
|----------|-----|-----------|
| `DATA_BUCKET` | todos | Bucket S3 com `events.csv` / `products.csv` |
| `PREDICTIONS_DYNAMODB_TABLE` | predict, API | Tabela de predições |
| `DRIFT_MONITOR_ENABLED` | predict | Dispara drift monitor ao final do predict (`true` em produção; `false` nos testes de integração) |
| `DRIFT_MONITOR_CLUSTER` / `TASK_DEFINITION` / `SUBNETS` / `SECURITY_GROUP` | predict | Destino do ECS RunTask do drift monitor |
| `PREDICTIONS_S3_URI` / `PREDICTIONS_FILENAME` | drift monitor | Snapshot avaliado — **injetados pelo `model_predict` no RunTask** (não confiar só na task definition) |
| `MONITORING_BUCKET` / `MONITORING_PREFIX` | drift monitor | Destino S3 do relatório parquet |
| `DRIFT_SNS_TOPIC_ARN` | drift monitor | Tópico SNS para alertas |
| `MODEL_PACKAGE_GROUP_NAME` | train, predict | SageMaker Model Registry group |
| `INFERENCE_IMAGE_URI` | train | URI ECR registrada no model package |
| `BASELINE_MODEL_DIR` | train | Diretório com `model.pkl` do case (default `/app/model` no container) |
| `BASELINE_MODEL_PREFIX` | train | Prefixo S3 do artefato baseline seed (default `models/purchase_propensity/case-baseline-v1`) |
| `AWS_REGION` | todos | Região AWS (default `us-east-1`) |
| `RECOMMENDATIONS_API_BASE_URL` | notebooks / api_tests | URL do API Gateway (opcional; fallback via `terraform output`) |
| `RECOMMENDATIONS_API_KEY` | notebooks / api_tests | API key para testes manuais (fallback via Terraform/SSM) |
| `LOAD_TEST_BATCH_SIZE` / `LOAD_TEST_ROUNDS` | notebook carga | Tamanho do batch e rounds por sessão (defaults 5 e 4) |
| `RECOMMENDATIONS_TEST_USER_ID` | api_tests | Usuário conhecido (default `u_0231`) |
| `RECOMMENDATIONS_TEST_COLD_START_USER_ID` | api_tests | Usuário cold start (default `u_9999`) |

Lista completa nos `load_config()` de cada `main.py` e nos outputs do Terraform (`terraform output`).

---

## Limitações conhecidas

- Predições desatualizadas entre execuções de `model_predict`.
- Replace DynamoDB O(n) — upsert do snapshot novo seguido de delete de chaves obsoletas; lento para catálogos grandes (~30k linhas levam vários minutos).
- Primeiro deploy na CI: `api_tests` exigem tabela de produção já populada (ver [Testes de integração](#testes-de-integração-aws-real)).
- **Versão do modelo e thresholds hardcoded** — simplificação do case; em produção seriam parâmetros (Registry + metadados do job de predição). Ver [Simplificações do case](#simplificações-do-case-vs-produção-real).
- **Triggers train/predict na CI** — simplificação para reproduzir o fluxo; em produção: EventBridge + Step Functions.
- **`model_drift_monitor` depende do trigger do `model_predict`** — não é previsto como job standalone na operação normal.
- Drift monitor e retreino automático não têm teste de integração end-to-end na CI (unitários + disparo desabilitado em integração).
- Subscription SNS por e-mail exige confirmação manual após o primeiro `terraform apply`.
- Rollback do CI reverte **infra Terraform**, não dados escritos nos testes de integração.
- `scikit-learn` pinado em 1.8.x para compatibilidade com artefato existente no S3.

---

## Referências rápidas

- Model card: `model/model_card.json`
- Planejamento de arquitetura: `PLAN.md`
- **Reproduzir em outro ambiente AWS:** [Passo a passo — reproduzir o case em outro ambiente AWS](#passo-a-passo--reproduzir-o-case-em-outro-ambiente-aws)
- Notebook de registro manual (legado): `notebooks/register_actual_model.ipynb` — substituído pelo seed automático em `model_train`
- Notebook de testes de endpoint: `notebooks/testing_endpoint.ipynb` — série interativa de testes da API (manual + automatizado); equivalente a `tests/api_tests/`
- Notebook de carga: `notebooks/api_load_test.ipynb`
