# Souza Silva (2024) — dissertação de mestrado, plantas daninhas com aprendizado profundo

## 1. Referência
Souza Silva, J. A. O. Dissertação de mestrado, Instituto Federal Goiano, 2024. Arquivo: `referencias/pdfs/Dissertação_JOSEF AUGUSTO OBERDAN SOUZA SILVA.pdf`. Título e link: conferir no PDF.

## 2. Grau de leitura
Íntegra parcial. Lido: capítulo II completo. Capítulo I: método da revisão, seção de daninhas, menções à cana, perguntas Q3 a Q6 e conclusão. Não lido o restante.

## 3. Tipo de fonte
Dissertação de mestrado (aceita).

## 4. Método
- Cap. I: revisão sistemática de 70 artigos (2018–2024); cerca de 30% tratam de daninhas. Limites apontados: falta de bases públicas e custo de anotação.
- Cap. II: detecção de daninhas em soja e feijão com YOLOv8s, Mask R-CNN (R101-DC5) e U-Net (ResNet50). Máscaras da U-Net geradas por limiar de tom verde.

## 5. Dados
VANT Phantom 3, voo a 20 m, GSD 0,88 cm, 793 imagens, 3.021 após aumento de dados, divididas em 2.270 / 370 / 381. Cultivos: soja e feijão. Não é cana.

## 6. Validação
Métricas sobre imagens, com divisão aleatória. Sem medição de campo.

## 7. Resultados
| Modelo | Resultado |
|---|---|
| YOLOv8s | mAP50 97%, precisão 99,7%, recall 99% |
| Mask R-CNN R101-DC5 | AP50 96,5% |
| U-Net ResNet50 | acurácia 96,1% (validação) |

## 8. Limitações para este projeto
- Cultura, altura de voo e pixel diferentes dos nossos.
- Hipótese minha, a verificar: o aumento parece feito antes da divisão, o que pode inflar as métricas por cópias da mesma imagem em treino e teste.
- Cana aparece só na revisão, em trabalhos de terceiros.

## 9. Aproveitar / não serve
- Aproveitar: panorama de métodos e o problema de anotação como argumento a favor de abordagem com pouca rotulagem.
- Não serve: números como expectativa de desempenho em cana.
