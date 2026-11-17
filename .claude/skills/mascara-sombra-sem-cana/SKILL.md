---
name: mascara-sombra-sem-cana
description: Gera as máscaras de sombra e de trechos longos sem cana, por talhão. Use ao implementar o módulo de máscaras.
---

# Máscaras de sombra e de trechos sem cana

Objetivo: separar onde a ausência de cana na imagem não indica falha real.

Passo a passo:
1. Sombra: combinar luminosidade baixa com o índice de vegetação, com limiares calculados por talhão (não globais).
2. Trechos longos sem cana: marcar sequências de fileira sem vegetação acima de um comprimento configurável.
3. Gravar as máscaras como camadas separadas, para uso no QGIS.
4. Estações dentro das máscaras ficam fora do cálculo do desvio e da contagem de falhas.

Regras:
- O módulo é independente do resto do motor, para reaproveitamento futuro em detecção de plantas daninhas. Não implementar detecção de daninhas agora.
- A sombra da própria fileira, colada à cana, pode deslocar o centro detectado: ver skill fusao-rgb-mds.
