---
name: fusao-rgb-mds
description: Quando o modelo de superfície for fornecido, funde a máscara das fileiras do RGB com a do modelo de superfície e usa o centro da interseção como eixo. Use ao implementar o módulo opcional de refinamento.
---

# Fusão RGB e modelo de superfície (opcional)

Status: hipótese de trabalho. Nenhuma fonte lida testou esta fusão para linhas de cana. Deve ser validada no piloto contra o motor só com RGB.

Motivo: a sombra colada à fileira escurece a borda da faixa no RGB e pode deslocar o centro. O modelo de superfície enxerga só altura, então a crista da fileira não depende da sombra. Também apoia trechos em que o mosaico ficou borrado ou com costura mal resolvida.

Passo a passo:
1. Verificar se o modelo de superfície foi fornecido. Se não, não fazer nada e seguir só com o RGB.
2. Reamostrar o modelo (cerca de 6 cm por pixel) e o ortomosaico (3 cm por pixel) para a mesma grade. Com fileiras de 45 a 50 cm, o modelo cobre cada faixa com cerca de 8 pixels de largura.
3. Gerar a máscara binária das fileiras no RGB e outra no modelo de superfície, cada uma com sua faixa (buffer) ao redor da fileira.
4. Sobrepor as duas e usar o centro da interseção como eixo da fileira.
5. Onde as máscaras divergirem de forma relevante, marcar a estação para revisão manual.

Pergunta aberta para o piloto: combinar por interseção (conservadora) ou por união (mais cobertura, mais ruído).
