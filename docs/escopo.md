# Escopo

## 1. Contexto do projeto
O usuário, Lucas Andrade, é coordenador de tecnologia agrícola em uma usina canavieira e trabalha com agricultura de precisão: mapeamento com drone, projeto de linhas para piloto automático e mapas temáticos em CAD e GIS.

Objetivo principal: reposicionar automaticamente as linhas de piloto automático de um projeto de plantio de cana, usando como referência a posição real das fileiras visíveis em um ortomosaico georreferenciado de 3 cm por pixel, detectando a deriva do trator ao longo de cada passada. O deslocamento não é um valor fixo por passada: é um perfil que varia ao longo da linha.

Objetivo secundário: gerar as linhas de falha de plantio (trechos de fileira sem cana acima de um comprimento mínimo informado pelo usuário) e permitir sua visualização.

Entradas: ortomosaico georreferenciado (3 cm por pixel), polígonos dos talhões (para recorte e processamento talhão a talhão), linhas de piloto projetadas (passadas de 3 m) e, opcionalmente, o modelo de superfície (cerca de 6 cm por pixel).

## 2. Geometria do plantio (premissas fixas)
- Cada passada do trator tem 3 m e leva duas fileiras, chamadas linhas gêmeas.
- As duas fileiras de uma passada ficam a 1,50 m de centro a centro. O implemento garante esse espaçamento, então o desvio entre as gêmeas é mínimo.
- Cada fileira é uma faixa de cana de 45 a 50 cm de largura.
- A linha de piloto automático percorre o eixo do par, a 0,75 m de cada fileira.
- Entre passadas vizinhas o espaçamento é garantido pelo GPS. É aí que aparecem sobreposição, vão e deriva, e é o foco da correção.
- As fileiras projetadas são geradas por offset de 0,75 m para cada lado da linha de piloto do projeto.

## 3. Decisões já tomadas
- Tecnologia: motor em Python independente do QGIS; interface como algoritmo da caixa de Processamento do QGIS (PyQGIS). HTML puro foi descartado para o processamento, porque ortomosaico tem gigabytes.
- Bibliotecas: rasterio (leitura por janelas), geopandas e shapely (linhas, talhões, offsets, amostragem), numpy e scipy (índice de vegetação, perfis, mediana, splines), scikit-image ou OpenCV (Otsu, morfologia), pyproj, PyQGIS.
- A linha projetada é usada como guia de busca: amostram-se perfis perpendiculares a ela, a cada 5 a 10 m, e o centro de cada faixa é procurado numa janela estreita ao redor, em vez de detectar fileiras do zero.
- O eixo do par é o ponto médio entre os centros das duas fileiras; o desvio lateral é medido contra a linha projetada, estação a estação; o perfil de desvio é suavizado (mediana e spline) e a linha corrigida é reconstruída.
- Trechos sem detecção confiável são interpolados e marcados; estações duvidosas são sinalizadas, nunca corrigidas em silêncio.
- Módulo de máscaras: detecção de sombra e de trechos longos sem cana. Estações dentro das máscaras ficam fora do cálculo do desvio e da contagem de falhas. O módulo é independente, para ser reaproveitado depois em detecção de plantas daninhas, que NÃO faz parte desta versão.
- Modelo de superfície: entrada opcional. Se fornecido, gera-se a máscara das fileiras no RGB e outra no modelo de superfície, sobrepõem-se as duas e usa-se o centro da interseção como eixo, para corrigir o resíduo da sombra da própria fileira e apoiar trechos de mosaico borrado. Sem o modelo, o motor roda só com RGB. Essa fusão é hipótese de trabalho, não resultado comprovado.
- Variedade e estágio da cultura NÃO são parâmetros: o operador que faz o mapeamento decide em campo o momento do voo.
- Falhas são objetivo secundário. O comprimento mínimo de falha é parâmetro do usuário (0,5 m é o valor de referência da literatura).

## 4. Regras de evidência (valem para todo o projeto)
- Nenhum resultado esperado, acurácia ou parâmetro entra sem fonte lida na íntegra. O que não tem fonte é marcado como hipótese.
- Ler artigos por completo, começando pelos métodos, e só depois os resultados.
- Fontes aceitas: artigo revisado por pares, tese de doutorado e dissertação de mestrado. Trabalho de conclusão de graduação NÃO é aceito.
- Validação contra medição de campo com RTK pesa mais do que contra outra marcação feita sobre a mesma imagem.
- Não comentar a qualidade, o georreferenciamento ou os parâmetros do ortomosaico: isso é responsabilidade do usuário, que domina o assunto.
