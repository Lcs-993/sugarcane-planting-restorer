# Linhas de Plantio de Cana: correção automática com ortomosaico

Ferramenta para reposicionar linhas de piloto automático de plantio de cana a partir de um ortomosaico georreferenciado de 3 cm por pixel, detectando a deriva do trator ao longo de cada passada. Como saída secundária, gera as linhas de falha de plantio acima de um comprimento mínimo definido pelo usuário.

## Status

v0.2.0. Três pacotes em `src/`:

- `linhas_plantio`: correção das linhas de piloto (fase 1).
- `deteccao_linhas`: detecção das fileiras só a partir do ortomosaico e do talhão. O perfil lateral pode vir do ExG + Otsu (padrão) ou da máscara de classes (`perfil_sobre: mascara` ou `--mascara`).
- `mascaras`: segmentação em cana, daninha, fundo e sombra (nível 1: classificador por pixel, local e gratuito). Treinado com pseudo-rótulos da própria detecção mais correção manual. Ver docs/escopo-mascaras.md.

Nada disso foi validado contra RTK ainda: os testes usam imagem sintética e mostram que o fluxo funciona, não a acurácia.

## Documentos

- docs/escopo.md: objetivo, escopo, premissas e decisões
- docs/arquitetura.md: módulos e fluxo
- docs/revisao-bibliografica.md: base científica e lacunas
- docs/plano-validacao.md: como medir a acurácia
- docs/guia-execucao.md: como rodar a detecção de fileiras no Windows (pastas de dados e arquivos .bat) e o fluxo da máscara de classes
- docs/escopo-mascaras.md: segmentação em classes (decisões, hipóteses e estado da implementação)

## Regra do projeto

Nenhum resultado ou parâmetro entra sem fonte lida na íntegra. O que não tem fonte é registrado como hipótese a validar.
