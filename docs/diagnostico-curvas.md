# Diagnóstico de fileiras em curva (ferramenta 2, `deteccao_linhas`)

Teste em **imagem sintética** com verdade exata. Mostra como o algoritmo se comporta; **não é acurácia de campo**
(que só sai da validação com RTK, `docs/plano-validacao.md`). O pacote não foi alterado: tudo foi feito por
configuração, e o "oráculo" é um desvio dentro do script de diagnóstico (`tests/deteccao_linhas/diagnostico_curvas.py`,
fora do pytest). Reproduzir: `python tests/deteccao_linhas/diagnostico_curvas.py base|varredura|oraculo|s <pasta>`.

## Cenário
Arcos concêntricos de raio central R (reta, 400, 200, 100, 50, 30 m) e uma curva em S (R=100 m, 300 m de comprimento).
Talhão de 40 m de largura (30 m para R=30), até 150 m de comprimento; passadas de 3 m com gêmeas a 1,50 m,
desvio de GPS entre passadas (σ=8 cm), pixel de 6 cm, faixas de 48 cm. Versão "real": falhas de 2 a 6 m, manchas de
daninha e ruído gaussiano. Versão "limpa": sem isso. Semente fixa.
Métricas: cobertura = fração do comprimento da verdade (na área útil) com linha detectada a ≤ 30 cm; erro = distância
assinada do ponto detectado à fileira verdadeira mais próxima.

## Resultado com a configuração padrão (regiao_m 150, bloco 10/10)
| Cenário (real) | cobertura ≤30 cm | detectado / interpolado / duvidoso | erro >25 cm (só detectado) | fileiras detectadas / verdade | erro de orientação |
|---|---|---|---|---|---|
| reta | 0,94 | 1,00 / 0,00 / 0,00 | 0,00 | 20 / 20 | 0° |
| R=400 | 0,50 | 0,34 / 0,53 / 0,13 | 0,10 | 46 / 20 | 7° |
| R=200 | 0,34 | 0,29 / 0,51 / 0,21 | 0,14 | 39 / 20 | 16° |
| R=100 | 0,08 | 0,31 / 0,40 / 0,29 | 0,17 | 12 / 20 | 35° |
| R=50 | 0,02 | 0,33 / 0,39 / 0,28 | 0,50 | 4 / 20 | 74° |
| R=30 | erro: nenhuma região com direção estimável | | | | |
| S (R=100) | 0,25 | 0,27 / 0,46 / 0,27 | 0,22 | 49 / 20 (12 com troca de fileira) | 22° |

## Só configuração (sem oráculo), cobertura ≤30 cm
| regiao_m (bloco 10/10, desvio máx. 90°) | reta | R=100 | R=50 | R=30 |
|---|---|---|---|---|
| 150 | 0,94 | 0,08 | 0,02 | erro |
| 75 | 0,93 | 0,24 | 0,03 | 0,03 |
| 50 | 0,94 | 0,27 | 0,08 | erro |
| 25 | 0,95 | 0,60 | 0,40 | 0,10 |
| 15 | 0,95 | 0,88 | 0,69 | 0,42 |
| 10 | 0,95 | 0,89 | 0,59 | 0,27 |

Com regiao_m 10 e bloco/passo 5/2,5: reta 0,97, R=100 0,88, R=50 0,82, R=30 0,63, S 0,95. Esses ganhos vêm com mais
fragmentação (1,9 a 3,2 pedaços por fileira verdadeira em curva) e erro >25 cm ≤ 0,3% nos pontos detectados.

## Causas (do código; as marcadas como hipótese não foram isoladas)
1. `orientacao.estimar_direcoes`: um único azimute por região de `regiao_m`. Numa curva a tangente gira
   `regiao_m / R` rad dentro da região; o erro de direção é de até metade disso. Medido: 7° (R=400), 16° (R=200), 35° (R=100).
2. `perfil_lateral.gerar_blocos`: blocos retos. Um desvio de direção δ espalha o perfil lateral em `comprimento_bloco_m · tan δ`
   (10 m e 5° dão 0,9 m, maior que a faixa de 0,48 m), e a flecha do arco no bloco é `L²/(8R)` (R=50, L=10: 25 cm).
3. `orientacao`: a herança por `desvio_angular_max_graus` (15°) troca direções corretas por mediana das vizinhas quando regiões
   vizinhas diferem mais que isso (visível em R=50, regiao 25: orientação 36° com 15° e 4° com 90°).
4. `rastreamento`: projeção reta com `tolerancia_ligacao_m` 0,30 m; o deslocamento lateral por passo é `passo²/(2R)`
   (hipótese: quebra de trilhas; observado como fragmentação, 2,3 trilhas por fileira em R=400).
5. Com a direção verdadeira por região (oráculo): regiao 150 → R=100 0,25; regiao 10, bloco 5/5 → R=100 0,93, R=50 0,79,
   R=30 0,58. Ou seja, a direção por região é o fator dominante; abaixo de R≈50 o bloco reto e o rastreamento passam a limitar.

## Raio crítico (critério: cobertura ≥ 0,80 e erro >25 cm ≤ 2% nos detectados)
- Configuração padrão: acima de 400 m (nenhum dos raios testados passa).
- Só configuração (regiao 10 a 15 m, bloco 5): cerca de 100 m com folga; R=50 passa só no limite (0,82 com regiao 10, bloco 5/2,5); R=30 não passa.
- Sintético: na imagem real, daninha, sombra e falhas longas podem piorar a direção em janelas de 10 a 15 m. Testar no talhão real antes de adotar.

## Mudanças sugeridas (não implementadas)
1. Direção por bloco, guiada pelo rastreamento (tangente extrapolada das últimas posições ligadas, refinada ±5°).
2. Perfil lateral em coordenadas curvilíneas (faixa curva em torno da trilha prevista), no lugar de retângulos retos.
3. Projeção quadrática no rastreamento e tolerância de ligação ligada à curvatura prevista.
4. Interim só de config: regiao_m 10–15, `area_minima_regiao_m2` ≈ 0,3·regiao_m², `desvio_angular_max_graus` alto,
   bloco 5 m e passo 2,5–5 m. Mais lento (reta 1 s → 8 s) e mais fragmentado.
5. Marcar como `duvidoso` os trechos de curvatura estimada acima de um limite.

## Limites
Imagem sintética de arcos e uma curva em S; sem sombra, sem declive, sem terraços, sem raio variável dentro da passada.
Uma semente por cenário. Nada aqui afirma acurácia de campo.
