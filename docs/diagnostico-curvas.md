# Diagnóstico de fileiras em curva (ferramenta 2, `deteccao_linhas`)

> **Atualização (branch `ajustes-curvas`)**: o diagnóstico abaixo (seções "Cenário" em diante) descreve o comportamento
> ANTES dos ajustes (`modo_blocos: regiao`). Esta seção traz o DEPOIS. Mesmo gerador sintético, mesmas sementes.
> **Ressalva: não foi possível rodar nos dados reais do talhão (a pasta do usuário não estava conectada).** A regressão
> no talhão 1031 (362 fileiras, mediana 7 cm contra as linhas recebidas, p95 16 cm, viés −6,8 cm, cobertura da
> referência 94,4 %, 1.241 pontos duvidosos) precisa ser repetida antes de adotar os novos padrões. Nada aqui é acurácia de campo.

## Antes x depois (versão "real": falhas, daninha e ruído; erro >25 cm só entre os pontos 'detectado')
| Cenário | cobertura ≤30 cm | erro >25 cm | fileiras detectadas / verdade | detectado / interpolado / duvidoso (depois) | tempo (s) |
|---|---|---|---|---|---|
| reta | 0,94 → 0,99 | 0,000 → 0,000 | 20 → 20 / 20 | 0,95 / 0,04 / 0,00 | 1,1 → 2,6 |
| R=400 | 0,50 → 0,99 | 0,102 → 0,000 | 46 → 20 / 20 | 0,92 / 0,07 / 0,00 | |
| R=200 | 0,34 → 0,99 | 0,139 → 0,000 | 39 → 21 / 20 | 0,95 / 0,04 / 0,01 | |
| R=100 | 0,08 → 0,98 | 0,167 → 0,000 | 12 → 20 / 20 | 0,96 / 0,04 / 0,00 | |
| R=50 | 0,02 → 0,97 | 0,500 → 0,002 | 4 → 22 / 20 (1 trilha troca de fileira) | 0,95 / 0,04 / 0,01 | |
| R=30 | erro → 0,60 | erro → 0,031 | erro → 15 / 13 | 0,62 / 0,23 / 0,15 | |
| S (R=100) | 0,25 → 0,99 | 0,216 → 0,000 | 49 → 20 / 20 | 0,97 / 0,03 / 0,00 | 2,6 → 5,5 |

Erro de orientação mediano: 7° / 16° / 35° / 74° (R=400/200/100/50) antes; ≤ 0,2° depois. Tempo da reta medido
isolado: 1,1 s → 2,6 s (≈ 2,4×); os tempos das curvas foram medidos com outro processo rodando. Para o talhão real
(27,3 ha) a estimativa é de mais ~1 min só na orientação (≈ 64 ms por janela de 15 m × ~1.300 janelas), **estimativa, não medição**.
Versão "limpa": mesma tendência (R=50 0,97; R=30 0,73, erro >25 cm 0,034). Figura: `curvas_antes_depois.png`.

## Raio crítico (critério: cobertura ≥ 0,80 e erro >25 cm ≤ 2 % dos 'detectado')
- Antes: acima de 400 m.
- Depois: passa em R = 400, 200, 100, 50 m (raio local das fileiras de 35 a 65 m no R=50) e na curva em S.
  R = 30 m (fileiras internas com raio local de 15 m, giro de ~200° no talhão) **não passa**: cobertura 0,60 e erro >25 cm 3,1 %.
  Raio crítico novo: entre 30 e 50 m (nos cenários sintéticos).

## O que mudou (detalhes em `docs/interfaces-deteccao.md`, seção 9, item 11)
1. Direção por janela de 15 m, com ajuste plano local e substituição de janela atípica (marcada como herdada), em vez de uma direção por região de 150 m.
2. Blocos de 10 m ao longo de linhas de corrente do campo de direção, com passo de 5 m, faixas de 15 m, folga lateral lida e núcleo aceito.
3. Qualidade: desvio à corda no lugar da reta de melhor ajuste; trecho com curvatura > 0,04 1/m vira 'duvidoso'.
Escolha pelo risco: a alternativa só de configuração (região 10–15 m, bloco 5 m) ganhou menos (R=50 0,69–0,82) e piora com daninha e falhas
longas em janela pequena; no modo `faixas` a direção é ajustada por vizinhança (atípicos substituídos), e o modo antigo continua disponível (`modo_blocos: regiao`).

## Parâmetros novos (todos hipótese, sem fonte lida)
`modo_blocos` (faixas), `passo_bloco_faixas_m` 5, `janela_direcao_m` 15, `passo_angulo_grosso_campo_graus` 3, `passo_angulo_fino_campo_graus` 0,5,
`max_pontos_janela_direcao` 30000, `raio_suavizacao_direcao_m` 25, `desvio_campo_max_graus` 8, `largura_corredor_m` 15,
`margem_lateral_bloco_m` 1,5, `curvatura_duvidosa_1_m` 0,04.

## Riscos
- Dados reais não rodados (ver ressalva). Em reta o padrão agora é o modo `faixas`: pode mudar o resultado do talhão 1031; comparar com `modo_blocos: regiao`.
- Janelas de 15 m são mais sensíveis a daninha, sombra e falhas longas que regiões de 150 m (mitigado pelo ajuste local, não eliminado).
- Em reta, `marcar_saltos_curvos` usa critério diferente do anterior: o número de pontos 'duvidoso' pode diferir.
- Tolerância a falhas mantida em metros (6 blocos de 5 m = 30 m); em R=50 uma trilha trocou de fileira (22 trilhas para 20 fileiras).
- Imagem sintética, uma semente por cenário, sem sombra, declive, terraço nem raio variável dentro da passada.

---

# Diagnóstico original (antes dos ajustes)

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

## Mudanças sugeridas (1, 2 (parcial), 3 (não necessária) e 5 foram implementadas; ver a atualização no início)
1. Direção por bloco, guiada pelo rastreamento (tangente extrapolada das últimas posições ligadas, refinada ±5°).
2. Perfil lateral em coordenadas curvilíneas (faixa curva em torno da trilha prevista), no lugar de retângulos retos.
3. Projeção quadrática no rastreamento e tolerância de ligação ligada à curvatura prevista.
4. Interim só de config: regiao_m 10–15, `area_minima_regiao_m2` ≈ 0,3·regiao_m², `desvio_angular_max_graus` alto,
   bloco 5 m e passo 2,5–5 m. Mais lento (reta 1 s → 8 s) e mais fragmentado.
5. Marcar como `duvidoso` os trechos de curvatura estimada acima de um limite.

## Limites
Imagem sintética de arcos e uma curva em S; sem sombra, sem declive, sem terraços, sem raio variável dentro da passada.
Uma semente por cenário. Nada aqui afirma acurácia de campo.
