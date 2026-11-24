# Revisão bibliográfica

Versão resumida. A revisão completa, com as fichas de cada fonte, será adicionada pelo usuário.

## 5. Base científica (resumo)
O que a literatura lida sustenta:
- Critério de falha de 0,5 m entre colmos e classes de qualidade do plantio (Stolf, 1986, citado em Rocha 2022): até 10% excelente, 11 a 20% normal, 21 a 35% subnormal, 36 a 50% ruim, acima de 50% péssimo.
- Rocha (2022), tese de doutorado, UFG: segmentação RGB planta contra fundo com KNN (K=3), 97,7% de acurácia, sem diferença significativa entre CART, LDA e KNN; erro de 3,02% no metro linear de falhas em 8,05 ha; mas pixel de cerca de 22 cm, erro lateral de 15 a 22 cm e referência traçada à mão sobre a imagem. Não serve como validação de posição de linha de piloto.
- Barbosa Júnior et al. (2021), Agronomy 11(12), 2578: pixel de 3,5 cm com planta de 0,5 m deu erro absoluto de cerca de 1,5 cm e R2 de 0,95 no comprimento de falhas; com planta de 1,7 m o R2 caiu para 0,2; falhas de 0,5 a 1 m ficam escondidas em perfilhamento e alongamento. Uma cultivar, falhas artificiais, medidas em campo.
- Ferreira et al. (2025), Smart Agricultural Technology 12, 101425: Excess Green, Otsu e projeção por rotação com filtro de Savitzky-Golay estimam o ângulo das fileiras com erro mediano de 0,9 grau; não estima posição lateral; propõe fundir marcações de especialistas com filtro de Kalman para ter referência com incerteza.
- Cavalcanti et al. (2023), Agronomy 13(10), 2545: falhas medidas com trena crescem com as colheitas por efeito do tráfego de máquinas; predominam falhas de 0,5 a 1,5 m.

- Ribeiro et al. (2024), Information Processing in Agriculture 11, 385-396, e Ribeiro (2023), dissertação: U-Net, LinkNet e PSPNet segmentam a faixa da fileira de cana (incluindo falhas) em imagem de VANT de cerca de 5 cm; Dice de 0,87 a 0,92 no mesmo conjunto e de 0,53 a 0,89 entre conjuntos; U-Net de 49.121 parâmetros próxima da maior; só ExG como entrada próximo ao RGB. Validação contra marcação de especialista, sem RTK.
- Rocha et al. (2023), Information Processing in Agriculture 10, 400-415: KNN por pixel (cana contra não cana), orientação por bloco e segmentos retos de 10 m; diferença lateral média de 0,15 a 0,22 m contra linhas desenhadas no QGIS; daninha não tratada.
- Souza Silva (2024), dissertação: daninhas em soja e feijão com YOLOv8s, Mask R-CNN e U-Net; não é cana; serve como panorama e como argumento do custo de anotação.
- Barrozo et al. (2025), trabalho em anais (4 p.): modelo de segmentação não identificado + transformada de Hough para falhas; sem validação de campo; peso baixo.

Fichas completas em `referencias/fichas/`. A decisão de método da máscara está em docs/escopo-mascaras.md.

O que NÃO tem fonte lida: correção de posição lateral de linha de piloto a partir de imagem (hipótese central do projeto); uso da linha projetada como guia de busca; fusão de máscara RGB com modelo de superfície; separação de cana e daninha em RGB por pixel ou por U-Net; tolerância do piloto automático como critério de aceitação.

Leituras pendentes: Maldaner et al. (2021), Biosystems Engineering 209, 64-73, que usa linhas georreferenciadas do plantio cruzadas com a imagem segmentada, pixel de 3 cm (não foi possível abrir o texto; só resumo); e estudos de paralelismo de plantio com piloto automático, como Molin et al. (2008), citado em tese da ESALQ.
