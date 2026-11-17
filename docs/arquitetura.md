# Arquitetura

Módulos, na ordem do fluxo. Cada um corresponde a um arquivo em src/linhas_plantio.

1. entrada: carrega ortomosaico (3 cm por pixel), polígonos dos talhões e linhas de piloto projetadas; confere se cada linha projetada cai dentro de um talhão.
2. preprocessamento: recorta o raster por talhão, com buffer interno para evitar borda e carreador; calcula o índice de vegetação (NDVI se houver infravermelho próximo; ExG ou VARI se for só RGB).
3. segmentacao: binariza o índice por talhão (Otsu calculado em cada talhão), separando cana de solo e palha.
4. mascaras: sombra (luminosidade baixa combinada com o índice de vegetação, por talhão) e trechos longos sem cana. Estações dentro das máscaras ficam fora do desvio e da contagem de falhas.
5. deteccao: gera as fileiras projetadas por offset de 0,75 m e amostra perfis perpendiculares à linha de piloto; procura o centro de cada faixa numa janela estreita ao redor da posição projetada.
6. desvio: ponto médio entre os centros das duas fileiras gêmeas e desvio lateral em relação à linha projetada, estação a estação.
7. qualidade: valida cada estação contra as regras geométricas.
8. reconstrucao: suaviza o perfil de desvio (mediana e spline) e reconstrói a linha corrigida; interpola trechos sem detecção confiável e os marca.
9. falhas: trechos de fileira sem cana, fora das máscaras, com comprimento igual ou maior que o mínimo informado pelo usuário.
10. mds_opcional: se o modelo de superfície (cerca de 6 cm por pixel) for fornecido, refina a faixa de cada fileira (ver skill fusao-rgb-mds).
11. saida: grava linhas corrigidas com atributos de qualidade e o arquivo de falhas, em geopackage, shapefile e DXF.

## Regras de qualidade
- O espaçamento detectado entre as duas fileiras gêmeas deve ficar próximo de 1,50 m; fora da tolerância, a estação é duvidosa.
- A largura detectada de cada faixa deve ficar próxima de 45 a 50 cm.
- Variação abrupta de desvio entre estações vizinhas é tratada como ruído de detecção, porque o trator não faz mudanças bruscas de trajetória.
- Trechos interpolados e passadas com muitas estações duvidosas são sinalizados para revisão manual.
- Verificar também o espaçamento entre fileiras de passadas vizinhas, para destacar sobreposição ou vão.
- Valores de tolerância são parâmetros configuráveis e hipóteses até serem definidos no piloto.
