# Case Técnico — Personalization Service

## Contexto

Nosso time é responsável por levar resultados de modelos de ML até o app, de forma personalizada por usuário. Isso envolve três frentes: ingestão de dados de comportamento, deploy/serving de modelos, e entrega (delivery) dos resultados via API para os times de produto consumirem.

Este case simula um pedaço real desse fluxo: você vai receber um modelo **já treinado** de propensão de compra e vai construir o serviço que o coloca em produção.

**Você NÃO precisa treinar ou melhorar o modelo.** O foco é 100% engenharia: arquitetura, API, tratamento de dados, qualidade de código e decisões de produção.

## O que você recebe

```
personalization-service-case/
├── data/
│   ├── events.csv        # histórico de interações usuário-produto (view, click, add_to_cart, purchase)
│   └── products.csv      # catálogo de produtos com metadados
├── model/
│   ├── model.pkl          # modelo já treinado (dict com model, scaler, feature_cols)
│   └── model_card.json    # documentação do modelo: features esperadas, tipos, notas
└── README.md
```

Carregando o modelo em Python:

```python
import pickle

with open("model/model.pkl", "rb") as f:
    artifact = pickle.load(f)

model = artifact["model"]          # sklearn LogisticRegression
scaler = artifact["scaler"]        # sklearn StandardScaler
feature_cols = artifact["feature_cols"]  # ordem exata das features esperadas
```

Consulte `model/model_card.json` para entender cada feature antes de implementar o cálculo delas. **Atenção especial à feature `user_affinity_match`**: ela não vem pronta em nenhum CSV — precisa ser derivada de `events.csv` + `products.csv`. O model card traz a definição de referência usada para gerar os dados; pequenas variações de critério são aceitáveis, desde que documentadas.

## O que construir

Um microserviço HTTP (API REST, síncrona) que:

1. **Ingestão / preparo de dados**
   Alguma forma de processar `events.csv` e `products.csv` em features consumíveis pelo modelo (pode ser um job/script que roda antes de subir a API, um passo de startup, ou o que você achar mais adequado — justifique a escolha).

2. **Endpoints da API**
   Exponha pelo menos os seguintes caminhos HTTP:

   | # | Método | Caminho | Descrição |
   |---|--------|---------|-----------|
   | 1 | `GET` | `/recommendations/{user_id}` | Retorna uma lista ranqueada de produtos recomendados para o usuário, com o score do modelo. |
   | 2 | `GET` | `/health` | Health check simples do serviço. |
   | 3 | `GET` | `/metrics` | Métricas básicas (bônus; formato Prometheus). |
   | 4 | `POST` | `/recommendations_filtered` | Mesma lógica de recomendação do endpoint principal, com filtros no corpo da requisição. O ranking continua baseado no score do modelo, aplicado ao subconjunto filtrado. |

   **Corpo da requisição (`POST /recommendations_filtered`):**

   ```json
   {
     "user_id": "u_0231",
     "limit": 10,
     "exclude_product_ids": ["p_001", "p_002"],
     "context": { "device": "mobile", "campaign": "black_friday" }
   }
   ```

   | Campo | Tipo | Obrigatório | Descrição |
   |-------|------|-------------|-----------|
   | `user_id` | `string` | sim | Identificador do usuário para personalização. |
   | `limit` | `integer` | não | Quantidade máxima de recomendações a retornar (padrão: você define e documenta). |
   | `exclude_product_ids` | `string[]` | não | Lista de `product_id` a remover do resultado (ex.: produtos já no carrinho). |
   | `context` | `object` | não | Metadados de contexto da requisição (ex.: `device`, `campaign`). Não precisam alterar o score do modelo neste case — registre nos logs estruturados e documente uso futuro no `SOLUTION.md`. |

   - Você decide quantos produtos retornar e como ranquear (mas o score do modelo deve ser a base do ranking).
   - Para `/recommendations_filtered`, documente no `SOLUTION.md` como cada filtro afeta o resultado e o que faria com `context` em produção.

3. **Cold start**
   O que acontece quando `user_id` não existe no histórico de `events.csv`? Descreva e implemente uma estratégia de tratamento.

4. **Testes**
   - Testes unitários cobrindo: cálculo de features, o endpoint principal, e o caso de cold start.
   - **Ao menos um teste de integração**: subir a aplicação (ex: via `TestClient` do FastAPI, ou um container real) e validar o fluxo completo de ponta a ponta — request HTTP real até resposta, sem mockar as camadas internas. O objetivo é garantir que as peças realmente funcionam juntas, não só isoladamente.

5. **Observabilidade**
   Este serviço vai rodar em produção — pensamos em observabilidade desde o início. Inclua:
   - **Logs estruturados** (ex: JSON) nas requisições principais, incluindo pelo menos `user_id`, latência da requisição, e se houve fallback de cold start.
   - **Alguma forma de métrica básica**, exposta via endpoint (`/metrics` no formato Prometheus é um bônus, mas não obrigatório) ou logada de forma agregável: contagem de requisições, taxa de erro, latência (p50/p95 já seria ótimo).
   - Não precisa integrar com uma stack real (Grafana, Datadog, etc.) — o importante é a informação existir e estar bem estruturada, pronta para ser consumida por uma stack de observabilidade depois.

6. **Documentação**
   Um `SOLUTION.md` (ou seção no README) explicando:
   - Como rodar o projeto
   - Decisões de arquitetura e trade-offs
   - O que você faria diferente com mais tempo
   - O que você loga/mede hoje e o que adicionaria com mais tempo (ex: alertas, tracing distribuído)

## Requisitos técnicos

- Linguagem: Python (o modelo é sklearn, então precisa ser Python >=3.12 para o serving)
- Framework de API livre
- Containerização com Docker é fortemente recomendada
- Não é necessário banco de dados real — pode processar os CSVs em memória ou usar SQLite/similar se preferir


## Prazo e entrega

Prazo de 1 semana (7 dias) ao contar da data de recebimento do case

Entregue via link de repositório próprio (não fazer FORK)

## Critérios gerais de avaliação

Vamos olhar para: clareza e organização do código, decisões de arquitetura, tratamento de edge cases, qualidade dos testes, e a clareza da documentação/raciocínio no `SOLUTION.md`. Não existe "solução perfeita" — queremos entender como você pensa e prioriza sob ambiguidade.

Qualquer dúvida sobre o escopo, pode assumir a interpretação que fizer mais sentido e documentar a decisão.

Boa sorte!
