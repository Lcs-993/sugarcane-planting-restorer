# CLAUDE.md

## Projeto
Ferramenta de correção de linhas de piloto automático de cana a partir de ortomosaico de 3 cm por pixel. Objetivo principal: gerar as linhas corrigidas. Objetivo secundário: gerar as linhas de falha de plantio. Detalhes em docs/escopo.md.

## Geometria do plantio
- Passada de 3 m com duas fileiras (linhas gêmeas) a 1,50 m de centro a centro.
- Cada fileira é uma faixa de 45 a 50 cm de largura.
- A linha de piloto fica no eixo do par, a 0,75 m de cada fileira.
- Entre passadas vizinhas quem garante o espaçamento é o GPS: é onde está o erro.

## Regras de evidência
- Não afirmar acurácia, parâmetro ou resultado sem fonte lida na íntegra. Hipótese deve ser marcada como hipótese.
- Ler artigos por completo, começando pelos métodos.
- Aceitar artigo revisado por pares, tese de doutorado e dissertação de mestrado. Não aceitar TCC de graduação.
- Validação contra medição de campo com RTK pesa mais do que contra marcação sobre a mesma imagem.

## Limites
- Não comentar qualidade, georreferenciamento ou parâmetros do ortomosaico: é responsabilidade do usuário.
- Variedade e estágio da cultura não são parâmetros: o operador decide o momento do voo.
- Daninha entra só como classe da máscara de segmentação (docs/escopo-mascaras.md), para ser excluída do perfil das fileiras. Mapeamento de daninha como produto continua fora. O módulo `src/mascaras` é independente.
- Sem API externa de IA no fluxo de processamento: modelos locais e gratuitos apenas.

## Estilo de código
- Motor em Python, independente do QGIS. A interface do QGIS só chama o motor.
- Ortomosaico lido por janelas, nunca inteiro na memória.
- Preservar o sistema de coordenadas dos dados de entrada.
- Cada módulo com teste em tests/.
- Trechos duvidosos e interpolados são marcados, nunca corrigidos em silêncio.
