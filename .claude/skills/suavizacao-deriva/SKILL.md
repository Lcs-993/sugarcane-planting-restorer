---
name: suavizacao-deriva
description: Suaviza o perfil de desvio lateral ao longo da passada e reconstrói a linha corrigida. Use ao implementar o módulo de reconstrução.
---

# Suavização da deriva

O deslocamento não é um valor fixo por passada: é um perfil que varia ao longo da linha. Uma reta inclinada indica rotação; um perfil ondulado indica trator serpenteando.

Passo a passo:
1. Montar o perfil de desvio por estação, ignorando as marcadas como duvidosas e as dentro de máscaras.
2. Aplicar filtro de mediana e, em seguida, spline ou média móvel.
3. Descartar saltos abruptos entre estações vizinhas como ruído de detecção, porque o piloto não faz curvas bruscas (limite de variação configurável; hipótese a definir no piloto).
4. Interpolar entre estações boas nos trechos sem detecção confiável e marcar o trecho como interpolado.
5. Reconstruir a linha corrigida somando o perfil suavizado à linha projetada.

Regras:
- Nunca inventar desvio em trecho sem estação boa nas duas extremidades: marcar para revisão manual.
- Gravar, por trecho, se o valor é detectado, estimado ou interpolado.
