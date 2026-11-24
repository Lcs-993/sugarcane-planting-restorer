# Rocha et al. (2023) — detecção de linhas de cana por KNN e gradiente RGB

## 1. Referência
Rocha et al., 2023. Information Processing in Agriculture, 10:400–415. Título completo e DOI: conferir no PDF `referencias/pdfs/Automatic detection and evaluation of sugarcane.pdf` (não transcritos aqui de memória).

## 2. Grau de leitura
Íntegra, começando pelos métodos.

## 3. Tipo de fonte
Artigo revisado por pares.

## 4. Método
- Classificador de pixels KNN (K=3), treinado com cerca de 667 amostras, separa cana de não cana.
- Orientação das linhas estimada por bloco de 200×200 px, com gradiente RGB e variância.
- Segmentos retos ajustados em faixas de 10 m.
- Falhas derivadas das lacunas entre plantas na linha.
- Daninhas não são tratadas.

## 5. Dados
Imagens de VANT de áreas de cana. Valores de altitude, pixel, área, cultivar e estágio: conferir no PDF antes de citar (não registrados nesta ficha).

## 6. Validação
Contra linhas desenhadas manualmente no QGIS sobre a mesma imagem. Não é medição de campo com RTK.

## 7. Resultados
| Métrica | Valor |
|---|---|
| Diferença lateral média (Ddif) | 0,15 a 0,22 m |
| Diferença lateral máxima | 0,51 m |

## 8. Limitações para este projeto
- Falha em curvas (segmentos retos).
- Árvores geram falsas fileiras.
- Daninhas não tratadas.
- Referência é marcação sobre a imagem, peso menor que RTK.
- Pixel e cultura podem diferir dos nossos: não transferir a acurácia.

## 9. Aproveitar / não serve
- Aproveitar: orientação por bloco e uso de comprimento de 10 m como ordem de grandeza (hipótese para nosso passo de bloco); ideia de classificador de pixels leve.
- Não serve: retas por faixa em curvas (já resolvido no modo `faixas`); supervisão manual por área.
