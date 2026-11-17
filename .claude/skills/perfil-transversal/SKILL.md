---
name: perfil-transversal
description: Amostra perfis perpendiculares à linha de piloto projetada e localiza o centro de cada faixa de cana. Use ao implementar o módulo de detecção guiada pela projeção.
---

# Perfil transversal

Entrada: raster binarizado (ou índice de vegetação) do talhão, linha de piloto projetada e fileiras projetadas por offset de 0,75 m.

Passo a passo:
1. Gerar estações ao longo da linha de piloto, em espaçamento configurável (hipótese de partida: 5 a 10 m).
2. Em cada estação, traçar um perfil perpendicular que cruze as duas fileiras e extrair a vegetação ao longo dele.
3. Procurar o centro de cada faixa de cana numa janela estreita ao redor da posição projetada (hipótese de partida: da ordem de 50 cm para cada lado, configurável).
4. Devolver, por estação: posição dos dois centros, largura de cada faixa e um indicador de confiança.

Regras:
- Ler o raster por janelas.
- Não detectar fileiras do zero: a linha projetada é o guia.
- Estação sem pico confiável devolve vazio e é marcada, não preenchida.
