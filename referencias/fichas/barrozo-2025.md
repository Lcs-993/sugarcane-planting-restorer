# Barrozo et al. (2025) — falhas de linha de plantio com Hough e segmentação semântica

## 1. Referência
Barrozo, M. A. S.; Silva, F. M.; Silva, E. F. S.; Verçosa, J. P. S.; Tavares, A. C. F. (UFAL). Identificação de falhas de linha de plantio utilizando a transformada de Hough e segmentação semântica em imagens de drone. Anais de evento, p. 140–143, https://proceedings.science/p/197165. Arquivo: `referencias/pdfs/IDENTIFICAÇÃO DE FALHAS DE LINHA DE PLANTIO UTILIZANDO A.pdf`. Nome do evento: não consta no PDF.

## 2. Grau de leitura
Íntegra (4 páginas), começando pelos métodos.

## 3. Tipo de fonte
Trabalho em anais de evento, 4 páginas. O PDF não informa se houve revisão por pares. Peso baixo: não é artigo de periódico, tese nem dissertação.

## 4. Método
- Modelo de segmentação semântica "previamente treinado", aplicado direto à imagem, sem filtros nem morfologia. O artigo não informa qual modelo, com que dados foi treinado nem quais classes tem.
- Máscara binarizada (vegetação 255, solo 0), lida com Rasterio.
- Transformada de Hough clássica e probabilística sobre a máscara para achar linhas retas (ângulos de −π/2 a π/2). Cita Canny como pré-processamento da versão probabilística.
- Cada linha é percorrida pixel a pixel; os trechos contínuos de solo viram falhas. Falhas abaixo de 50 cm são descartadas. Exporta shapefile.
- Comparação feita no QGIS: linhas de plantio desenhadas à mão, índice GLI, limiar binário, vetorização da vegetação e diferença entre linha e vegetação. Também descarta falhas abaixo de 50 cm.

## 5. Dados
Uma área de cana. Não informa GSD, altura de voo, câmera, tamanho da área, cultivar nem estágio.

## 6. Validação
Nenhuma medição de campo. A "comparação" é entre dois métodos, ambos sobre a mesma imagem, e um deles usa linhas desenhadas à mão. Não há métrica de acurácia.

## 7. Resultados
| Método | Falhas | Comprimento médio da falha |
|---|---|---|
| Hough + segmentação | 32,12% | 0,88 m |
| QGIS (linhas à mão + GLI) | 28,2% da área | 1,05 m |

Os dois métodos divergem entre si e não há referência para saber qual está mais perto do real.

## 8. Limitações para este projeto
- Modelo de segmentação não identificado: não é reproduzível.
- Hough detecta só linhas retas: não serve em curva (já tratado no modo `faixas`).
- Não estima posição lateral nem a compara com nada.
- Sem validação de campo e sem dados da imagem.

## 9. Aproveitar / não serve
- Aproveitar: mesma ordem de operações que pretendemos (máscara de planta, depois falhas ao longo da linha, corte em 0,5 m, que coincide com o critério de Stolf); GLI como índice alternativo ao ExG, a testar como hipótese.
- Não serve: os percentuais como referência; Hough como detector de linhas; o modelo de segmentação, por não ser identificado.
