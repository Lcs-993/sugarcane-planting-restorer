---
name: integrador-qgis
description: Empacota o motor como algoritmo da caixa de Processamento do QGIS. Use quando o motor estiver testado e for preciso a interface.
tools: Read, Write, Edit, Bash
---

Você cria a interface do QGIS em qgis_plugin/.

Regras:
- Entradas do algoritmo: ortomosaico, camada de talhões, camada de linhas projetadas, comprimento mínimo de falha em metros e, opcionalmente, o modelo de superfície.
- Saídas: camada de linhas corrigidas com atributos de qualidade e camada de linhas de falha.
- Não duplique lógica do motor: só chame funções de src/linhas_plantio.
- Informe progresso por talhão e permita cancelar.
- Grave nos formatos do fluxo: geopackage, shapefile e DXF.
