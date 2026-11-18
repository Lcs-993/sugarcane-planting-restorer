# Escopo da detecção de linhas (segunda ferramenta)

Pacote `src/deteccao_linhas`, tratado como um segundo plugin. É independente de `src/linhas_plantio` (fase 1) e do QGIS. Vale a regra de evidência do projeto (docs/escopo.md, seção 4): parâmetro sem fonte lida é hipótese configurável, nunca fato.

## 1. Motivação

Ao rodar o motor da fase 1 nos dados reais (fazenda 1031 Santa Maria, talhão de 27,3 ha, ortomosaico RGB em EPSG:31983), as 303 linhas projetadas recebidas vieram espaçadas a cerca de 1,50 m entre si. São as fileiras, não os eixos de piloto de 3 m que o motor esperava. Nas imagens, as fileiras são faixas descontínuas de brotos verdes sobre palha, com touceiras e manchas verdes de erva fora da linha. Guiado pela linha projetada, o motor da fase 1 marcou cerca de 61% das estações como duvidosas.

Em vez de adaptar o motor guiado, o usuário decidiu criar uma ferramenta que recria as linhas do zero, vendo só a imagem.

## 2. Objetivo

Detectar, a partir só do ortomosaico e do polígono do talhão, a posição de cada fileira de plantio ao longo do talhão e gerar uma linha por fileira detectada, com marcação de confiança por trecho.

Fora do objetivo desta ferramenta: eixos de piloto, pares de fileiras, linhas corrigidas, linhas de falha de plantio, máscaras de erva como módulo próprio, modelo de superfície e plugin QGIS.

## 3. Entradas e saídas

| Entrada | Formato | Requisito |
|---|---|---|
| Ortomosaico | GeoTIFF RGB | Lido por janelas, nunca inteiro na memória. |
| Talhões | GeoPackage ou shapefile, polígonos | Campo identificador (`Config.campo_id_talhao`). |
| Linhas de referência (só na comparação) | GeoPackage ou shapefile, linhas | Nunca lidas pela detecção. |

Ortomosaico e talhões (e a referência, na comparação) devem estar no mesmo CRS projetado em metros. A ferramenta não reprojeta; se divergirem, para com erro que lista cada camada e seu CRS. Saídas herdam o CRS da entrada.

Saída da detecção: um GeoPackage com
- camada `fileiras`: uma linha por fileira detectada (`id_fileira`, `talhao`, `comprimento_m`, `confianca_media`, `frac_duvidosa`);
- camada `trechos`: um ponto por bloco e fileira (`id_fileira`, `posicao_m`, `status` em `detectado`, `interpolado` ou `duvidoso`, `confianca`).

Saída da comparação: relatório (JSON e resumo no terminal) e, opcionalmente, camada de diferenças por trecho. Detalhes em docs/interfaces-deteccao.md.

## 4. Premissas fixas de geometria

- Dentro de uma passada, as duas fileiras ficam a 1,50 m de centro a centro.
- A distância entre fileiras de passadas vizinhas é garantida pelo GPS e varia; é onde estão a sobreposição, o vão e a deriva. Por isso o espaçamento de 1,50 m vale como referência do ajuste de periodicidade, com tolerância, e não como regra rígida entre todas as fileiras.
- Cada fileira é uma faixa de 45 a 50 cm de largura.
- Variedade e estágio da cultura não são parâmetros; o operador decide o momento do voo.

## 5. Decisões já tomadas

1. Saída principal: só as fileiras, uma linha por fileira detectada. Sem pares e sem eixos de piloto.
2. Detecção cega: nenhuma linha projetada é usada ao detectar. A comparação com as linhas recebidas é feita depois, em módulo separado (`comparacao`).
3. Pacote novo no mesmo repositório, `src/deteccao_linhas`, com testes (`tests/deteccao_linhas/`), CLI e documentação próprios, separado de `src/linhas_plantio`.

Decisões de projeto desta versão, ainda não validadas: RGB apenas; índice ExG por padrão; Otsu calculado em cada talhão; trechos duvidosos marcados e nunca preenchidos em silêncio.

## 6. O que a literatura sustenta e o que é hipótese

### 6.1 Sustentado por fonte lida
Ferreira et al. (2025), Smart Agricultural Technology 12, 101425: Excess Green, limiarização de Otsu e projeção por rotação com filtro de Savitzky-Golay para estimar a orientação das linhas, com erro mediano de 0,9 grau no ângulo, nas condições do artigo. Sustenta apenas a parte da orientação. O artigo não estima posição lateral de fileira. O valor de 0,9 grau não é transferido para este projeto.

### 6.2 Hipótese, sem fonte lida
Todas as etapas abaixo são hipóteses de trabalho. Não há resultado esperado afirmado.

| Hipótese | Conteúdo |
|---|---|
| H1 (central) | A posição lateral de cada fileira pode ser obtida de um perfil lateral calculado por integração longa da vegetação ao longo da direção das fileiras, em blocos de comprimento configurável. A integração deve atenuar a descontinuidade e a erva fora da linha. |
| H2 | Um pente de periodicidade 1,50 m, com fase local e tolerância, localiza as fileiras no perfil lateral e absorve o salto entre passadas. |
| H3 | A direção das fileiras pode variar por região do talhão; estimá-la por região (e não uma vez por talhão) basta para fileiras aproximadamente retas dentro da região. |
| H4 | Ligar posições de blocos consecutivos, com tolerância a falhas curtas, reconstitui fileiras contínuas. |
| H5 | A confiança por trecho (contraste do pico, coerência longitudinal, largura, ajuste ao pente) separa trechos bons de duvidosos. A fórmula é hipótese. |
| H6 | ExG com Otsu por talhão separa brotos verdes de palha o suficiente para o perfil lateral. A erva verde passa pelo limiar e é tratada por H1 e H5, não por máscara. |

Todos os valores numéricos de `Config` são hipóteses (tabela em docs/interfaces-deteccao.md, seção 4), a ajustar no piloto.

## 7. Limitações esperadas

- Descontinuidade das fileiras. Faixas de brotos com vãos reduzem o contraste do perfil em blocos curtos. Blocos longos ajudam, mas diluem variações rápidas de posição (H1 contra resolução longitudinal). Blocos sem pico confiável ficam duvidosos ou, se cercados por blocos bons dentro do limite de falha, interpolados e marcados.
- Erva verde. Touceiras e manchas fora da linha passam pelo índice de vegetação e podem formar picos falsos ou deslocar o centro de uma faixa. A defesa é a coerência longitudinal, a largura esperada da faixa e o ajuste ao pente. Não há máscara de erva nesta versão; a ferramenta pode falhar onde a erva for contínua e paralela às fileiras.
- Otsu por talhão. Com muita erva ou palha, o limiar de um talhão pode não separar os brotos. O limiar usado é registrado no resumo.
- Curvas e terraços. A direção é estimada por região e o perfil lateral supõe fileiras aproximadamente retas dentro do bloco. Em curva forte, a integração longa espalha a faixa e o ajuste de largura e confiança tende a reprovar o trecho. Esta versão não modela fileira curva dentro do bloco.
- Fileiras que mudam de ordem em curvas (numeração) e fileiras cortadas por falha longa viram fileiras separadas.
- A posição lateral absoluta depende de H1; sem validação em campo ela não é conhecida.

## 8. Comparação com as linhas recebidas

As linhas recebidas são uma referência secundária. Não são medição de campo com RTK e podem ter erro próprio. Uma diferença entre fileira detectada e linha recebida não é, por si, erro da detecção. A validação final continua sendo contra RTK, conforme docs/plano-validacao.md (referência RTK em pontos amostrais; o erro lateral da fileira detectada é medido contra ela). O plano de validação existente trata de linha corrigida e deve ganhar uma seção equivalente para fileiras detectadas; esse ajuste não é feito aqui.

O módulo `comparacao` é independente e roda depois da detecção. Para cada trecho detectado, mede a distância lateral à linha recebida mais próxima. Relata:

- distância lateral absoluta: média, mediana e percentil 95;
- viés assinado (média das distâncias com sinal), para distinguir deslocamento global de dispersão;
- taxa de pareamento: fração dos trechos detectados com linha recebida dentro da distância máxima de pareamento (hipótese configurável);
- cobertura da referência: fração do comprimento das linhas recebidas com fileira detectada pareada;
- os mesmos números por status (`detectado`, `interpolado`, `duvidoso`) e por fileira;
- declaração fixa no relatório: "referência secundária, não é RTK".

Nenhum limite de aceitação é definido: nenhuma fonte lida estabelece tolerância para piloto automático. Os números descrevem concordância entre duas fontes, não acurácia.

## 9. Integração futura

Um plugin QGIS (`qgis_plugin`, fora desta etapa) chamaria `executar_deteccao` e `executar_comparacao`, sem lógica de geometria própria.
