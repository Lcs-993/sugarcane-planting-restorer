---
name: validacao-rtk
description: Calcula o erro lateral da linha corrigida contra pontos de referência medidos em campo com RTK. Use ao validar o motor.
---

# Validação contra RTK

Siga docs/plano-validacao.md.

Passo a passo:
1. Ler a linha corrigida e os pontos de referência de campo.
2. Para cada estação, medir o desvio lateral entre a linha e a referência.
3. Reportar erro médio, percentil 95 e porcentagem de estações dentro da tolerância do piloto automático (valor a definir).
4. Repetir para três configurações: linha projetada sem correção, motor só com RGB, motor com RGB e modelo de superfície.
5. Reportar a taxa de estações duvidosas e de trechos interpolados.
6. Gerar tabela e gráficos de erro.

Regras:
- Linha traçada sobre a imagem é referência secundária e deve ser declarada como tal.
- Com mais de um especialista, fundir as marcações com filtro de Kalman estático (Ferreira et al., 2025).
- Nunca declarar acurácia sem dizer contra o quê foi medida.
