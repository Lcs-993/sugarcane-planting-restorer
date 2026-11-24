# Escopo do módulo de máscaras (segmentação em classes)

Pacote novo `src/mascaras`, independente de `src/deteccao_linhas` e do QGIS. Produz uma máscara de classes que a detecção de linhas passa a ler no lugar do ExG + Otsu. Vale a regra de evidência do projeto (docs/escopo.md, seção 4): parâmetro sem fonte lida é hipótese configurável, nunca fato.

## 1. Motivação

Na detecção atual, a etapa ExG + Otsu (hipótese H6 de docs/escopo-deteccao.md) chama de vegetação tudo que é verde. Erva fora da linha forma picos falsos ou desloca o centro da faixa. Em cana rala, o limiar de Otsu do talhão pode não separar os brotos. As demais etapas (orientação, perfil lateral, pente, curvas, rastreamento, confiança) não dependem de como a máscara foi feita. Por isso a troca é feita só nesta etapa.

## 2. Decisões tomadas (consenso de 2026-11-24)

1. Segmentação em classes por pixel. Não detecção de plantas: na brotação e no perfilhamento as touceiras se fundem numa faixa e não há planta individual com contorno definido. O projeto também não precisa contar plantas.
2. Rótulo de planta, não de faixa. Ribeiro et al. (2024) rotulam a faixa da fileira incluindo as falhas. Aqui isso esconderia as falhas, que são objetivo secundário do projeto.
3. Dois níveis, ambos gratuitos e executados localmente:
   - Nível 1: classificador por pixel (scikit-learn), na linha de Rocha et al. (2023) e do plugin AIGeo Classificador IA.
   - Nível 2: rede de segmentação pequena do tipo U-Net, na linha de Ribeiro et al. (2024) e Ribeiro (2023), exportada em ONNX.
   O nível 2 só é desenvolvido se o nível 1 não separar a daninha da cana na comparação da seção 8.
4. Modelo treinado uma vez, com vários talhões, e reaproveitado. Sem rotulagem a cada análise.
5. Rótulos de treino por pseudo-rótulo gerado pela própria detecção atual (seção 6), mais correção manual pontual no QGIS.
6. Sem API externa. Modelos de linguagem (OpenCode, API da Nvidia e similares) não entram no fluxo de processamento: não devolvem posição em centímetros, não são reprodutíveis para validação contra RTK e exigiriam enviar as imagens para fora. Podem ser usados só como assistentes de programação.
7. O plugin AIGeo Classificador IA (`referencias/plgins/`) é referência de interface (coleta de amostras por polígono e refino por polígono). Seu código é GPL-3 e não é copiado. Ele lê o raster inteiro na memória, o que este projeto não faz.

## 3. Classes

| Código | Classe | Observação |
|---|---|---|
| 0 | ignorado | sem dado, fora do talhão, ou pixel sem rótulo confiável no treino |
| 1 | cana | só o pixel de planta de cana |
| 2 | daninha | qualquer vegetação que não é cana |
| 3 | fundo | solo e palha |
| 4 | sombra | |

## 4. Entradas e saídas

| Item | Formato | Requisito |
|---|---|---|
| Ortomosaico | GeoTIFF RGB | Lido por janelas, nunca inteiro na memória. |
| Talhões | GeoPackage ou shapefile | Mesmo CRS do ortomosaico. Sem reprojeção. |
| Modelo | arquivo do nível 1 ou `.onnx` do nível 2 | Acompanhado de um arquivo de metadados: classes, bandas, resolução de trabalho, versão e talhões de treino. |
| Saída | GeoTIFF de uma banda, `uint8`, códigos da seção 3 | Mesmo CRS e grade alinhada à do ortomosaico na resolução de trabalho. Opcional: GeoTIFF de probabilidade da classe cana. |

O arquivo do nível 1 é serializado por joblib (pickle). Só carregar modelos gerados pelo próprio projeto.

## 5. Integração com a detecção de linhas

- Nova fonte `FonteMascara` com a mesma interface de `FonteBinaria` (`area`, `ler_janela(bounds, resolucao_m) -> JanelaRaster`).
- `valores = True` onde a classe é cana. Hipótese: sombra e ignorado ficam com `validade = False` (fora do perfil), como as máscaras previstas em docs/escopo.md; daninha e fundo ficam válidos e `False`.
- `Config.perfil_sobre` ganha o valor `mascara`, com o caminho do GeoTIFF de classes. O padrão continua `binario` (ExG + Otsu), que segue disponível como alternativa.
- Nenhuma outra etapa da detecção muda.

## 6. Pseudo-rótulos

Gerados a partir de uma execução da detecção atual (ExG + Otsu) em talhões escolhidos:

1. Só entram trechos com status `detectado` e confiança acima de um limiar (hipótese). Trechos `interpolado` e `duvidoso` e seus vizinhos ficam como ignorado.
2. Pixel verde dentro da faixa da fileira (largura de 45 a 50 cm, premissa do projeto) → cana.
3. Pixel verde numa zona de margem ao redor da faixa → ignorado, porque o perfilhamento passa da faixa nominal. Largura da margem: hipótese.
4. Pixel verde fora das faixas e das margens → daninha.
5. Pixel não verde → fundo.
6. Sombra: não sai da detecção. Rotulada à mão ou por regra de brilho (hipótese), a decidir na implementação.

Correção manual: polígonos por classe desenhados no QGIS sobrescrevem o pseudo-rótulo, no estilo das abas de amostras e de refino do AIGeo.

Risco conhecido: o modelo herda os erros do método atual. Por isso nenhuma métrica de avaliação usa pseudo-rótulo (seção 8).

## 7. Os dois níveis

### 7.1 Nível 1: classificador por pixel
- Atributos por pixel: R, G, B, ExG e, a testar, GLI (usado por Barrozo et al., 2025). Atributos de vizinhança (média e desvio em janela pequena) a testar como opção. Todos hipótese.
- Modelo: Random Forest como padrão (hipótese). Rocha (2022) não achou diferença significativa entre CART, LDA e KNN para planta contra fundo. Nenhuma fonte lida trata cana contra daninha.
- Treino e inferência em CPU, por janelas.

### 7.2 Nível 2: U-Net pequena
- Entrada RGB, com ExG como alternativa. Ribeiro (2023) obteve resultado próximo ao do RGB usando só ExG.
- Tamanho da rede: Ribeiro (2023) relata uma configuração de 49.121 parâmetros próxima da maior. Fica como ordem de grandeza inicial, não como resultado esperado.
- Recortes de 256 × 256 px como ponto de partida (Ribeiro et al., 2024). A 3 cm por pixel isso dá cerca de 7,7 m de lado. Tamanho e sobreposição dos recortes na inferência: hipótese.
- Treino em PyTorch, com GPU local ou Google Colab (pendente, seção 10). Exportação para ONNX. Inferência com onnxruntime em CPU, por janelas com sobreposição.
- Treino com talhões misturados. Ribeiro et al. (2024) mostram queda forte ao testar em área não vista quando o treino é de uma área só.

## 8. Avaliação

1. Divisão por talhão: treino e teste nunca no mesmo talhão.
2. Conjunto de teste manual, revisado, com daninha e cana rala de propósito. Métrica por classe (IoU e matriz de confusão) só sobre ele.
3. Avaliação final pela tarefa: rodar a detecção de linhas com três máscaras (ExG + Otsu, nível 1, nível 2) e medir contra `dados/referencia_campo`:
   - `fileira_rtk`: erro lateral da fileira detectada (média, mediana, percentil 95, viés);
   - `falha_rtk`: falhas, no desenho de Barbosa Júnior et al. (2021);
   - taxa de trechos duvidosos e interpolados.
4. Nenhum limite de aceitação é fixado: nenhuma fonte lida o estabelece.

## 9. O que a literatura sustenta e o que é hipótese

### 9.1 Sustentado por fonte lida (fichas em `referencias/fichas/`)
- Segmentação de linhas de cana com U-Net em imagem de VANT, com queda de desempenho entre áreas sem diversidade de treino (Ribeiro et al., 2024; Ribeiro, 2023). Pixel de cerca de 5 cm e validação por Dice contra marcação de especialista, sem RTK. Os valores não se transferem.
- U-Net pequena e ExG como entrada única com resultado próximo ao do RGB (Ribeiro, 2023).
- Classificador leve por pixel separa planta de fundo (Rocha et al., 2023; Rocha, 2022). Daninha não é tratada.
- Corte de falha em 0,5 m (Stolf, 1986, citado em Rocha, 2022), também usado por Barrozo et al. (2025).

### 9.2 Hipótese, sem fonte lida
| Hipótese | Conteúdo |
|---|---|
| M1 (central) | Uma máscara de cana que exclui a daninha reduz picos falsos e deslocamento de centro no perfil lateral e diminui os trechos duvidosos. |
| M2 | O classificador por pixel separa cana de daninha o suficiente para M1. |
| M3 | O contexto espacial da U-Net separa cana de daninha melhor que o pixel isolado. |
| M4 | Pseudo-rótulos de trechos confiáveis bastam para treinar sem rotulagem manual extensa. |
| M5 | Um modelo treinado uma vez em vários talhões vale para talhões novos da mesma região. |

## 10. Pendências
1. Ambiente de treino do nível 2: GPU local ou Google Colab.
2. Escolha dos talhões de treino e de teste.
3. Regra para a classe sombra.

## 11. Fora deste escopo
Detecção de plantas individuais, modelos de linguagem ou de visão por API, transformada de Hough, operações morfológicas como refino (Ribeiro, 2023, não viu melhora), e plugin QGIS.
