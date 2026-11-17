# Linhas de Plantio de Cana: correção automática com ortomosaico

Ferramenta para reposicionar linhas de piloto automático de plantio de cana a partir de um ortomosaico georreferenciado de 3 cm por pixel, detectando a deriva do trator ao longo de cada passada. Como saída secundária, gera as linhas de falha de plantio acima de um comprimento mínimo definido pelo usuário.

## Status

Fase 0: documentação, base científica e estrutura do projeto. Ainda não há código do motor.

## Documentos

- docs/escopo.md: objetivo, escopo, premissas e decisões
- docs/arquitetura.md: módulos e fluxo
- docs/revisao-bibliografica.md: base científica e lacunas
- docs/plano-validacao.md: como medir a acurácia

## Regra do projeto

Nenhum resultado ou parâmetro entra sem fonte lida na íntegra. O que não tem fonte é registrado como hipótese a validar.
