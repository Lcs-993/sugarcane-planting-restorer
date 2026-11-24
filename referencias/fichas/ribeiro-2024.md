# Ribeiro et al. (2024) — U-Net/LinkNet/PSPNet para linhas de cana

## 1. Referência
Ribeiro, J. B.; Silva, R. R.; Dias Júnior, J. D.; Escarpinati, M. C.; Backes, A. R. Automated detection of sugarcane crop lines from UAV images using deep learning. Information Processing in Agriculture 11:385–396, 2024. DOI 10.1016/j.inpa.2023.04.001.

## 2. Grau de leitura
Íntegra, começando pelos métodos.

## 3. Tipo de fonte
Artigo revisado por pares.

## 4. Método
- Segmentação em duas classes (linha de cana versus solo) com U-Net, LinkNet e PSPNet, encoder VGG16.
- Recortes de 256×256 px.
- Rótulo: região da fileira desenhada por especialista, incluindo as falhas.
- Refino por transformada de Radon testado e não superou a rede.

## 5. Dados
Mosaicos de VANT de cana em estágios de cana-planta e soca, GSD aproximado de 5,3 cm. Quatro mosaicos (A–D) mais um conjunto externo. Número de recortes: ver dissertação (ficha ribeiro-2023-dissertacao).

## 6. Validação
Contra marcação do especialista sobre a imagem (Dice). Sem RTK.

## 7. Resultados
| Situação | Dice |
|---|---|
| Treino e teste no mesmo conjunto | 0,87 a 0,92 |
| Treino em um conjunto, teste em outro | 0,53 a 0,89 |
| Treino com conjuntos misturados | 0,84 a 0,92 |

## 8. Limitações para este projeto
- Generalização entre áreas cai muito sem diversidade de treino.
- Daninhas geralmente tratadas como planta.
- Pixel de 5,3 cm contra nossos 3 cm.
- Sem validação de posição em metros.

## 9. Aproveitar / não serve
- Aproveitar: rótulo como faixa da fileira; misturar áreas no treino; validar em talhão não visto.
- Não serve: usar o Dice como medida de erro de posição da linha de piloto.
