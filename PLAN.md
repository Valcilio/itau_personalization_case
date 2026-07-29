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
    - Uma tabela DynamoDB que guarda o snapshot atual das predições (sempre substituído a cada nova execução do model_predict);
    - Um API Gateway REST para servir nossa API com API keys nativas (usage plan);
    - Um VPC Link conectando o API Gateway ao NLB interno, que encaminha para o ALB e o ECS da API. Rotas: /health (GET), /recommendation(s)/{user_id} (GET), /metrics (GET) e /recommendation(s)_filtered (POST);
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
        também será responsável por realizar todas as conexões que forem necessárias com a AWS. Ele irá:
            - salvar o output final no S3 sempre com um nome único (timestamp + hash), para nunca sobrescrever arquivos anteriores;
            - salvar o mesmo output no DynamoDB fazendo replace completo da tabela já existente (apaga o snapshot anterior e grava o novo).
        modelhandler.py: vai extrair do model package o model.pkl e o scaler.pkl, chamar as classes de featureengineer.py e modelrunner.py para
        gerar as features e depois realizar a predição em cima das features geradas, por fim vai devolver esses dados.
    Utils:
        modelrunnerlogger.py: irá ter as configurações de logging equivalente ao que já temos no model trainer para todas as classes do
        model_predict, exceto por costumer.py.
    Main.py: será nosso entrypoint que vai usar o awsconnector.py e o modelhandler.py para gerar as predições, salvar no S3 o output
    versionado e substituir o conteúdo da tabela DynamoDB com todas as predições geradas.

Persistência do output do model_predict:
    - S3: histórico imutável por execução (`predictions_<timestamp>_<hash>.csv`).
    - DynamoDB: estado atual consumível pela API; a cada run o conteúdo da tabela é totalmente substituído pelo novo resultado.

Vale lembrar que o model_predict irá rodar dentro de um cluster ECS.

# RECOMMENDATIONS API

Explicando melhor a API de consumo:

    Entities:
        user.py: irá validar as informações obtidas através da API, no caso teremos a possibilidade de receber requests do tipo GET ou POST.
            - Se for /recommendation/{user_id} (GET) ela deve validar se o user_id é entendido como válido seguindo o padrão de "u_0231" e similar;
            - Se for /recommendation_filtered (POST) ela deve validar o user_id com o mesmo padrão e também os filtros enviados no body;
                - Filtros planejados para POST /recommendation_filtered:
                        Fluxo geral:
                            1. Buscar as predições do user_id no DynamoDB (ou aplicar cold start se o usuário não existir);
                            2. Aplicar os filtros abaixo sobre o conjunto de produtos ranqueados;
                            3. Ordenar pelo recommendation_score do modelo (desc);
                            4. Aplicar o limit e retornar o resultado.
                        Filtros do case (obrigatórios no contrato da API):
                            - user_id (obrigatório): identifica o usuário alvo da recomendação;
                            - limit (opcional): quantidade máxima de produtos retornados após o ranking filtrado;
                            - exclude_product_ids (opcional): remove product_ids da resposta (ex.: itens já no carrinho ou já visualizados);
                            - context (opcional): metadados da requisição (ex.: device, campaign). Neste case não altera o score do modelo;
                            deve ser registrado em logs estruturados e documentado para uso futuro em produção
                            (ex.: re-ranking por canal, campanhas, experimentos A/B).
                        Filtros extras planejados (usando o schema de products/predictions):
                            - categories / exclude_categories: inclui ou remove produtos por categoria
                            (beleza, casa, eletronicos, esporte, livros, moda);
                            - min_price / max_price: restringe a faixa de preço;
                            - min_avg_rating: remove produtos abaixo da avaliação mínima;
                            - min_popularity_score: remove produtos pouco populares;
                            - min_recommendation_score: corta itens com score do modelo abaixo do limiar;
                            - only_affinity_match: mantém apenas produtos com user_affinity_match = 1;
                            - exclude_cold_start: quando houver fallback de cold start, permite omitir esses itens
                            se a API quiser expor apenas scores “quentes”.
                        Validação esperada no POST:
                            - user_id no padrão u_XXXX;
                            - limit > 0 quando informado;
                            - exclude_product_ids / categories como listas de strings válidas;
                            - faixas numéricas coerentes (ex.: min_price <= max_price; scores entre 0 e 1 quando aplicável).
            - Se for /health ou metrics, não precisaremos válidar nada.

    Use Cases:
        recomendationsretriever.py: vai recuperar as Top10 recomendações para o usuário solicitado, a conexão vai ser passada como um atributo para essa classe;
        recommendationsfilter.py: vai filtrar as recomendações com base no que for passado caso tenha sido uma requisição usando o /recommnedation_filtered;
        recommendationsstructurer.py: responsável por estruturar os dados para que possam ser devolvidos adequadamente quando recomendado;
            - se for uma request no /recommendation o dado deve devolver apenas o que foi pedido em README.md;
            - se for uma request no /recommendation_filtered, deve devolver tudo que vem do MongoDB, naturalmente passando pelos filtros passados no request.
    
    Gateways:
        awsconnector.py: vai lidar com todas as conexões e operações que precisarmos fazer na AWS;
        recommendationshandler.py: vai orquestrar as classes vindas dos casos de uso com recommendations no nome;

    Utils:
        apilogger.py: irá ter as configurações de logging equivalente ao que já temos no model trainer para todas as classes do
        recommendations_api, exceto por user.py.

    main.py: vai servir como entrypoint chamando as classes da camada de gateways para fazer todo o processo de recuperar e devolver a(s) recomendações solicitadas.
        - precisaremos ter os 4 entrypoints planejados aqui:
            - /health: vai indicar se a API está funcional;
            - /metrics: precisará trazer as métricas solicitadas no README.md;
            - /recommendation/{user_id}: vai precisar devolver as recomendações solicitadas para o usuário especificado;
            - /recommendation_filtered: vai precisar devolver as recomendações solicitadas com base nos filtros passados.

Lembrando que aqui teremos um cluster ECS onde esse código vai rodar, um application load balancer para que ele possa se conectar em um API Gateway via VPC Link e o API Gateway e VPC Link propriamente ditos,
Vale lembrar que o cluster ECS aqui vai precisar de uma configuração de autoscaling sendo que, se ele usar até 70% da sua memória ou CPU, precisa começar a criar outras tasks até um máximo de 20 tasks.
Fora que é um serviço online e não batch como os outros dois casos.

OBS1: Importante lembrar que os dados recuperados daqui devem vir da tabela de predições do DynamoDB que criamos anteriormente.
OBS2: Outro ponto importante é que a API deve poder ser acessada de qualquer lugar da internet sem limitação de IP, porém deve requerir uma API Key ou algum outro método de autenticação.
OBS3: Lembre que para lidar com cold_start cases, nós iremos substituir o recommendation score pelo popularity score e também precisamos sempre devolver o cold_start_flag indicando se o usuário é cold_start ou não.
