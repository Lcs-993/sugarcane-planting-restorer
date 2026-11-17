---
name: falhas-minimas
description: Gera as linhas de falha de plantio acima do comprimento mínimo informado pelo usuário. Use ao implementar a saída secundária de falhas.
---

# Falhas de plantio

Critério de referência: falha é espaço maior que 0,5 m entre colmos ao longo da linha (Stolf, 1986, citado em Rocha, 2022 e Barbosa Júnior et al., 2021). O comprimento mínimo é parâmetro do usuário, em metros.

Passo a passo:
1. Cruzar a linha ajustada de cada fileira com a máscara binária: onde há cana é planta, onde não há é candidato a falha.
2. Remover candidatos dentro das máscaras de sombra e de trechos sem cana.
3. Manter só os trechos com comprimento igual ou maior que o mínimo do usuário.
4. Gravar uma linha por falha, com atributos: talhão, passada, fileira e comprimento em metros.
5. Calcular o percentual de falha por talhão: comprimento de falhas dividido pelo comprimento total das linhas.

Atenção: a literatura lida mostra que vegetação em crescimento esconde falhas de 0,5 a 1 m em perfilhamento e alongamento (Barbosa Júnior et al., 2021). Esta é uma saída secundária, e a decisão do momento do voo é do operador.
