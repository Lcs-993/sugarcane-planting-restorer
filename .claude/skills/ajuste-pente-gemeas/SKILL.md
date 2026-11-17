---
name: ajuste-pente-gemeas
description: Casa o par de fileiras gêmeas com o modelo de dois dentes (1,50 m entre centros, faixa de 45 a 50 cm) e devolve o ponto médio como eixo da passada. Use ao calcular o eixo do par.
---

# Ajuste do par de fileiras gêmeas

Modelo: duas faixas de 45 a 50 cm de largura, com centros a 1,50 m, repetindo a cada passada de 3 m. O eixo do par é o ponto médio entre os dois centros.

Passo a passo:
1. Receber os dois centros detectados na estação (skill perfil-transversal).
2. Verificar a distância entre eles: deve ficar próxima de 1,50 m. Fora da tolerância, marcar a estação como duvidosa (tolerância configurável; hipótese a definir no piloto).
3. Verificar a largura de cada faixa contra 45 a 50 cm.
4. Calcular o ponto médio e o desvio lateral em relação à linha de piloto projetada.
5. Quando só uma fileira for detectada, estimar o eixo a partir dela usando o espaçamento de 0,75 m e marcar a estação como estimada.

O espaçamento de 1,50 m é garantido pelo implemento, então o desvio entre as gêmeas é mínimo e serve de filtro de qualidade, não de correção.
