A solução será feita da seguinte forma:

# Versionamento de código e CICD

Vamos fazer o versionamento de código usando o github com CI/CD via github actions.

O CI irá:
    - Rodar o Pytest;
    - Rodar o Pylint;
    - Gerar novas versões das imagens docker;
    - Gerar uma nova tag;

o CD irá:
    - Rodar o terraform na pasta terraform;
    - Mandar as imagens docker para seus respectivos repositórios docker;

Já dentro da AWS vamos ter o seguinte:

    - Um ECS que gera uma nova versão do modelo e registra no sagemaker model registry como latest;
    - Um bucket S3 onde serão salvas as versões dos modelos pelo job do sagemaker que gera a nova versão a cada run;
    - Um bucket S3 que vai conter os dados para gerar as features para fazer predict do modelo e treinar o modelo (nossos csvs de event e product nesse repositório);
    - Um ECS que vai rodar o modelo atual que temos já treinado após ele ser versionado no model registry (vamos registrar ele manualmente com o terraform após subir ele no S3) e uma pasta no bucket anterior para salvar os resultados da predição dele;
    - Um API Gateway para servir nossa API;
    - Um VPC Link para conectar o API Gateway que geramos com o ALB e um ECS que vai rodar o código da API, essa API terá 4 rotas: /health (GET), /recommendation/{user_id} (GET), /metrics (GET) e /recommendation_filtered (POST);
    - Por fim teremos nossos logs sendo registrados no cloudwatch e uma pasta no bucket que tem as predições salvas para salvar os dados de métricas e outputs consumidos com timestamps e requests ids.