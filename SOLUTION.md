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

# MODEL PREDICT

Explicando melhor o model_predict:

    Entities:
        costumer.py: irá apenas validar se os dados gerados gerados no featureengineer.py estão de acordo com o schema
        esperado pelo modelo, a classe desse arquivo irá ser chamada apenas pelo featureengineer no final do seu processo.
    Use Cases:
        featureengineer.py: vai usar os dados de events e products que vai receber via chamada para gerar as features necessárias
        para o modelo e vai chamar o costumer.py para poder validar se o dataset final está de acordo com o que é esperado.
        Também é esperado aqui seja feita o scaling dos dados usando um scaler que ela vai receber como atributo igual aos datasets.
        modelrunner.py: vai receber o modelo e usá-lo para obter as probabilidades de compra de cada produto por cliente e depois
        devolverá o dataset completo com todas as probabilidades para cada produto.
    Gateways:
        awsconnector.py: recuperará os dados de eventos e produtos que já temos no S3, recuperara o model package (sempre hardcoded para a versão 5 dele) e
        também será responsável por realizar todas as conexões que forem necessárias com a AWS, ele também irá mandar os dados de outputs gerados para o S3.
        modelhandler.py: vai extrair do model package o model.pkl e o scaler.pkl, chamar as classes de featureengineer.py e modelrunner.py para
        gerar as features e depois realizar a predição em cima das features geradas, por fim vai devolver esses dados.
    Utils:
        modelrunnerlogger.py: irá ter as configurações de logging equivalente ao que já temos no model trainer para todas as classes do
        model_predict, exceto por costumer.py.
    Main.py: será nosso entrypoint que vai usar o awsconnector.py e o modelhandler.py para gerar as predições e salvar no S3 o output com todas elas.

Vale lembrar que o model_predict irá rodar dentro de um cluster ECS.

# PREDICTIONS RETRIEVER API

Explicando melhor a API de consumo:

