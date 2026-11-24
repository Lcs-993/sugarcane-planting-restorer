# Ribeiro (2023) — dissertação de mestrado, segmentação de linhas de cana com CNNs

## 1. Referência
Ribeiro, J. B. Dissertação de mestrado, 2023. Arquivo: `referencias/pdfs/Deteccao_linhas_plantio.pdf`. Instituição e link: conferir no PDF.

## 2. Grau de leitura
Íntegra parcial. Lidos: trabalhos relacionados, metodologia (cap. 4), resultados (cap. 5) e conclusão (cap. 6). Não lidos: fundamentos (cap. 2) e apêndices.

## 3. Tipo de fonte
Dissertação de mestrado (aceita).

## 4. Método
- Mesma base do artigo Ribeiro 2024, com mais experimentos.
- Quatro mosaicos (A–D) em recortes 256×256, descartando recortes com menos de 80% de dados úteis; 678, 3.291, 1.552 e 2.162 recortes.
- Comparação de redes, transfer learning, número de blocos da U-Net, índices de vegetação, operações morfológicas.
- Treino de 50 épocas, Adam, taxa 0,001.

## 5. Dados
GSD aproximado de 5 cm (eBee, câmera 1 polegada); mosaico L do LAPIX, câmera Canon G9X, aproximadamente 5 cm, rotulado só nos pixels da cultura (406 recortes úteis). Cana-planta e soca.

## 6. Validação
Contra marcação de especialista (Dice), k-fold com k=10 na primeira etapa. Sem RTK.

## 7. Resultados
| Experimento | Resultado |
|---|---|
| U-Net, mesmo conjunto, k-fold | Dice 0,867 a 0,923 |
| U-Net treinada em E(500) (mistura), teste em A–D | 0,96 / 0,94 / 0,94 / 0,87 (config. 01, Figura/Tab. 14) |
| U-Net config. 09 (5×16 filtros, 49.121 parâmetros) | próxima da config. 01 |
| Índices de vegetação junto com RGB | ganho pequeno |
| Só ExG como entrada | Dice próximo ao do RGB (ex.: 0,931 / 0,918 / 0,918 / 0,876 na config. 01) |
| Modelo treinado em A–D testado no conjunto L | 0,68 |
| Modelo treinado em L, teste em L | 0,90 a 0,92 |
| Erosão, dilatação, abertura, fechamento | sem melhora |

## 8. Limitações para este projeto
- O modelo aprende a convenção de rótulo do especialista.
- Falhas pequenas e fileiras isoladas no meio do talhão têm segmentação ruim.
- Não valida posição em campo.
- Autor aponta poucos conjuntos disponíveis (seis).

## 9. Aproveitar / não serve
- Aproveitar: ExG como entrada suficiente; U-Net pequena viável; diversidade de treino; escolher convenção de rótulo antes de rotular.
- Não serve: acurácia como estimativa do nosso erro; operações morfológicas simples como refino.
