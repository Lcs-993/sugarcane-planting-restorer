# Interfaces da detecção de linhas

Só interfaces: assinaturas, entradas, saídas, tipos e erros. Nenhum corpo de implementação (`...`). Segue docs/escopo-deteccao.md. Pacote `src/deteccao_linhas`, independente de `src/linhas_plantio`: não importa nada dele. Parte do contrato de CRS e da estrutura de `Config` é repetida de propósito (ver ponto a decidir 7).

## 1. Convenções gerais

- Raster e camadas no mesmo CRS projetado em metros. Sem reprojeção. Saídas herdam o CRS da entrada.
- Ortomosaico lido por janelas. Nenhuma função recebe ou devolve o raster do talhão inteiro. Exceção controlada: a estimativa de orientação lê uma região (`regiao_m`, hipótese de 150 m de lado) como uma janela só, na resolução de trabalho.
- Processamento talhão a talhão. Distâncias em metros.
- Referência de direção do talhão `u_ref`: vetor unitário `(ux, uy)` (leste, norte), da direção dominante das regiões. Ângulos de orientação são módulo 180 graus (azimute a partir do norte, horário). O sentido do vetor de cada região é escolhido de modo que `dot(u_regiao, u_ref) > 0`; isso evita inversão de sentido perto de 0 e 180 graus.
- Quadro local de um bloco: ponto `(s, t)` vale `origem + s*u + t*n`, com `n` a normal à esquerda de `u`. `t` positivo à esquerda, negativo à direita, no sentido de `u`.
- Numeração das fileiras: coordenada global `t_g = dot(p - c_ref, n_ref)`, com `c_ref` o centroide da área útil do talhão e `n_ref` a normal à esquerda de `u_ref`. Cada fileira recebe a mediana de `t_g` dos seus pontos. As fileiras são ordenadas por essa mediana, crescente, ou seja, da direita para a esquerda olhando no sentido de `u_ref`. `id_fileira = f"{talhao}-F{n:04d}"`, com `n` a partir de 1. A numeração é só uma chave de ordem: em curvas e terraços a ordem pode trocar e não indica vizinhança.
- Cada fileira é digitalizada no sentido de `u_ref`. `posicao_m` é a distância ao longo da fileira a partir do primeiro ponto.
- Status: `detectado` (pico confiável no bloco); `interpolado` (sem pico utilizável, com bloco bom nos dois lados e dentro do limite de falha; posição por interpolação linear); `duvidoso` (pico com confiança abaixo do limiar ou reprovado nas regras de qualidade; a posição medida é mantida e marcada). Bloco sem pico e sem condição de interpolar não gera ponto: a fileira termina ali.
- Nada é corrigido ou preenchido em silêncio. Valor numérico sem fonte lida é hipótese.
- Testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.

## 2. Erros (src/deteccao_linhas/tipos.py)

```python
class ErroDeteccaoLinhas(Exception): ...            # base
class ErroConfig(ErroDeteccaoLinhas): ...           # parâmetro ausente, desconhecido ou fora de faixa
class ErroLeitura(ErroDeteccaoLinhas): ...          # arquivo inexistente, formato, campo identificador ausente, caminho não gravável
class ErroCRS(ErroDeteccaoLinhas): ...              # CRS ausente, não projetado em metros ou divergente
class ErroContrato(ErroDeteccaoLinhas): ...         # geometria de tipo errado, vazia ou inválida, id duplicado, banda inexistente
class ErroDeteccao(ErroDeteccaoLinhas): ...         # direção não estimável, talhão sem pixels válidos, nenhuma fileira detectada
```

Mensagem de `ErroCRS` (formato): `CRS divergente: ortomosaico=EPSG:31983; talhoes=EPSG:4674. Divergem do ortomosaico: talhoes. Reprojete as camadas antes de rodar.`

## 3. Configuração e tipos

### 3.1 config.py

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

@dataclass(frozen=True)
class Config:
    """Todos os valores são HIPÓTESES, a ajustar no piloto (tabela da seção 4).
    As premissas de geometria (1,50 m; 45 a 50 cm) são do projeto."""
    # Índice e binarização
    indice: Literal["exg", "vari"] = "exg"
    variante_exg: Literal["normalizado", "bruto"] = "normalizado"
    bandas_rgb: tuple[int, int, int] = (1, 2, 3)      # numeração do rasterio, base 1
    resolucao_trabalho_m: float = 0.06                # redução por média de área; >= resolução nativa
    n_bins_otsu: int = 256
    buffer_interno_m: float = 5.0
    perfil_sobre: Literal["binario", "indice"] = "binario"

    # Orientação
    regiao_m: float = 150.0                           # lado das regiões de estimativa de direção
    area_minima_regiao_m2: float = 2000.0             # regiões menores herdam direção (marcada)
    passo_angulo_grosso_graus: float = 1.0
    passo_angulo_fino_graus: float = 0.1
    sg_janela: int = 11                               # ímpar, em amostras do perfil de projeção
    sg_ordem: int = 3
    desvio_angular_max_graus: float = 15.0            # contra a mediana das regiões vizinhas

    # Perfil lateral
    comprimento_bloco_m: float = 10.0
    passo_bloco_m: float = 10.0                       # < comprimento_bloco_m gera sobreposição
    bin_lateral_m: float = 0.06
    subtrecho_m: float = 1.0                          # para a coerência longitudinal
    limiar_presenca_subtrecho: float = 0.10

    # Pente
    espacamento_fileiras_ref_m: float = 1.50          # premissa; vale como referência com tolerância
    tolerancia_espacamento_m: float = 0.20
    semijanela_dente_m: float = 0.25
    dentes_por_janela_fase: int = 4
    proeminencia_min: float = 0.10                    # em fração de vegetação do perfil
    largura_faixa_min_m: float = 0.45                 # premissa
    largura_faixa_max_m: float = 0.50                 # premissa
    tolerancia_largura_m: float = 0.15

    # Rastreamento
    tolerancia_ligacao_m: float = 0.30
    max_blocos_falha: int = 3
    comprimento_min_fileira_m: float = 30.0

    # Qualidade
    limiar_confianca: float = 0.50
    limite_variacao_m: float = 0.30                   # contra a mediana local, após remover a tendência
    janela_mediana: int = 3                           # em blocos, ímpar
    pesos_confianca: tuple[float, float, float, float] = (0.3, 0.3, 0.2, 0.2)
    # ordem dos pesos: contraste, coerência longitudinal, largura, ajuste ao pente

    campo_id_talhao: str = "id"

@dataclass(frozen=True)
class ConfigComparacao:
    """Hipóteses da comparação com a referência secundária."""
    distancia_max_pareamento_m: float = 0.50          # abaixo de metade do espaçamento, para não parear com a fileira vizinha
    campo_id_referencia: str | None = None
    usar_status: tuple[str, ...] = ("detectado", "interpolado")   # status entrando nas estatísticas globais

def carregar_config(caminho: Path | None) -> Config:
    """Lê YAML. None devolve os padrões.
    Raises: ErroConfig (chave desconhecida, tipo errado, valor fora de faixa,
    sg_janela ou janela_mediana par, passo_bloco_m > comprimento_bloco_m,
    resolucao_trabalho_m < 0, pesos que não somam 1, largura_faixa_min_m > largura_faixa_max_m)."""
    ...

def carregar_config_comparacao(caminho: Path | None) -> ConfigComparacao:
    """Idem, para ConfigComparacao. Raises: ErroConfig."""
    ...
```

`config.yaml` de exemplo repete os campos, cada valor comentado como hipótese.

### 3.2 tipos.py (dataclasses compartilhadas)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import numpy as np
from affine import Affine
from pyproj import CRS
from shapely.geometry import LineString, Polygon, MultiPolygon

Status = Literal["detectado", "interpolado", "duvidoso"]

@dataclass(frozen=True)
class Talhao:
    id: str
    poligono: Polygon | MultiPolygon

@dataclass(frozen=True)
class DadosEntrada:
    caminho_ortomosaico: Path
    crs: CRS
    talhoes: tuple[Talhao, ...]

@dataclass(frozen=True)
class JanelaRaster:
    valores: np.ndarray              # 2D; float32 (índice) ou bool (binário)
    validade: np.ndarray             # 2D bool; False em nodata ou fora do polígono útil
    transform: Affine

@dataclass(frozen=True)
class AreaTalhao:
    talhao: Talhao
    poligono_util: Polygon | MultiPolygon     # talhão com buffer interno negativo
    bounds: tuple[float, float, float, float]

@dataclass(frozen=True)
class DirecaoFileiras:
    azimute_graus: float             # [0, 180), a partir do norte, horário
    vetor: tuple[float, float]       # (ux, uy) unitário, sentido alinhado a u_ref
    confianca: float                 # 0 a 1
    herdada: bool                    # True se vinda de vizinhas (marcada, nunca silenciosa)

@dataclass(frozen=True)
class Regiao:
    id_regiao: str
    talhao: str
    poligono: Polygon | MultiPolygon          # recorte da área útil
    direcao: DirecaoFileiras | None           # None antes da estimativa

@dataclass(frozen=True)
class Bloco:
    id_bloco: str
    id_regiao: str
    origem: tuple[float, float]      # (x, y) do quadro local
    u: tuple[float, float]
    n: tuple[float, float]           # normal à esquerda de u
    s0_m: float                      # início do bloco ao longo de u, no quadro da região
    comprimento_m: float
    t_min_m: float
    t_max_m: float
    s_global_m: float                # dot(centro - c_ref, u_ref); ordem de processamento

@dataclass(frozen=True)
class PerfilLateral:
    bloco: Bloco
    t_m: np.ndarray                  # centros dos bins laterais
    vegetacao: np.ndarray            # fração de vegetação integrada ao longo do bloco; NaN sem dado
    coerencia: np.ndarray            # fração de subtrechos com vegetação no bin (0 a 1); NaN sem dado
    cobertura: float                 # fração do bloco com pixels válidos (0 a 1)

@dataclass(frozen=True)
class PosicaoFileira:
    id_bloco: str
    t_m: float                       # no quadro local do bloco
    x: float
    y: float
    largura_m: float | None
    proeminencia: float
    coerencia: float
    ajuste_pente: float              # 0 a 1; 1 = dente na posição esperada do pente
    espacamento_vizinha_m: float | None   # à posição vizinha à esquerda; None na última
    salto: bool                      # espaçamento fora da tolerância (típico entre passadas)
    confianca: float                 # 0 a 1

@dataclass(frozen=True)
class ResultadoPente:
    bloco: Bloco
    posicoes: tuple[PosicaoFileira, ...]     # ordenadas por t crescente
    fase_m: float | None                     # fase global do pente; None se não ajustável

@dataclass(frozen=True)
class PontoFileira:
    id_bloco: str
    x: float
    y: float
    posicao_m: float
    status: Status
    confianca: float

@dataclass(frozen=True)
class Trilha:
    """Sequência de posições ligadas entre blocos; ainda sem id e sem avaliação final."""
    pontos: tuple[PontoFileira, ...]

@dataclass(frozen=True)
class FileiraAvaliada:
    talhao: str
    geometria: LineString            # sentido de u_ref
    pontos: tuple[PontoFileira, ...]
    comprimento_m: float
    confianca_media: float
    frac_duvidosa: float

@dataclass(frozen=True)
class Fileira:
    id_fileira: str
    avaliada: FileiraAvaliada

@dataclass(frozen=True)
class ResumoDeteccao:
    talhao: str
    limiar_otsu: float
    n_regioes: int
    n_regioes_direcao_herdada: int
    n_blocos: int
    n_fileiras: int
    n_trilhas_descartadas: int       # abaixo de comprimento_min_fileira_m
    n_pontos_por_status: dict[str, int]
```

## 4. Parâmetros hipótese

Nenhum tem fonte lida. As premissas geométricas (1,50 m; 45 a 50 cm) são do projeto.

| Parâmetro | Valor inicial | Observação |
|---|---|---|
| indice, variante_exg | exg, normalizado | Escolha de projeto; ExG consta em Ferreira et al. (2025), a variante não foi verificada |
| resolucao_trabalho_m | 0,06 | Hipótese |
| n_bins_otsu | 256 | Hipótese |
| buffer_interno_m | 5,0 | Hipótese |
| perfil_sobre | binario | Hipótese |
| regiao_m | 150,0 | Hipótese |
| area_minima_regiao_m2 | 2000 | Hipótese |
| passo_angulo_grosso_graus, passo_angulo_fino_graus | 1,0; 0,1 | Hipótese |
| sg_janela, sg_ordem | 11; 3 | Hipótese; o artigo usa Savitzky-Golay, parâmetros não transferidos |
| desvio_angular_max_graus | 15,0 | Hipótese |
| comprimento_bloco_m | 10,0 | Hipótese central (H1); compromisso entre integração e resolução longitudinal |
| passo_bloco_m | 10,0 | Hipótese |
| bin_lateral_m | 0,06 | Hipótese |
| subtrecho_m, limiar_presenca_subtrecho | 1,0; 0,10 | Hipótese |
| tolerancia_espacamento_m | 0,20 | Hipótese; maior que a da fase 1 porque inclui a variação entre passadas |
| semijanela_dente_m | 0,25 | Hipótese |
| dentes_por_janela_fase | 4 | Hipótese |
| proeminencia_min | 0,10 | Hipótese |
| tolerancia_largura_m | 0,15 | Hipótese; fileira descontínua alarga ou estreita a largura integrada |
| tolerancia_ligacao_m | 0,30 | Hipótese |
| max_blocos_falha | 3 | Hipótese |
| comprimento_min_fileira_m | 30,0 | Hipótese |
| limiar_confianca | 0,50 | Hipótese |
| limite_variacao_m | 0,30 | Hipótese |
| janela_mediana | 3 | Hipótese |
| pesos_confianca | 0,3; 0,3; 0,2; 0,2 | Hipótese; a fórmula de confiança (H5) também é hipótese |
| distancia_max_pareamento_m (comparação) | 0,50 | Hipótese |

## 5. Fluxo de dados

```
entrada.carregar_entrada                      -> DadosEntrada (valida CRS, ids, geometrias)
por talhão:
  indice_binarizacao.abrir_fonte_indice + recortar_talhao -> FonteIndice, AreaTalhao
  indice_binarizacao.calcular_limiar_otsu + abrir_fonte_binaria -> FonteBinaria
  orientacao.dividir_em_regioes               -> list[Regiao]
  orientacao.estimar_direcoes                 -> list[Regiao] com direcao (marca as herdadas); u_ref
  perfil_lateral.gerar_blocos                 -> list[Bloco]
  por bloco:
    perfil_lateral.calcular_perfil            -> PerfilLateral
    pente.ajustar_bloco                       -> ResultadoPente
  rastreamento.rastrear                       -> list[Trilha]
  qualidade.avaliar_trilhas                   -> list[FileiraAvaliada]
  saida.numerar_fileiras                      -> list[Fileira]
saida.gravar_geopackage                       -> GeoPackage (fileiras, trechos)

comparacao.comparar (separado, depois)        -> RelatorioComparacao
```

## 6. Módulos

Ajustes em relação à lista sugerida: (a) `indice_binarizacao` inclui `recortar_talhao`, porque a área útil só serve à leitura do índice; (b) a numeração das fileiras fica em `saida`, por ser convenção de saída e depender das fileiras já avaliadas; (c) `tipos.py` e `config.py` como na fase 1.

### 6.1 entrada (src/deteccao_linhas/entrada.py)

```python
def carregar_entrada(caminho_ortomosaico: Path, caminho_talhoes: Path, cfg: Config) -> DadosEntrada:
    """Lê metadados do raster e os talhões; valida o contrato.
    Raises:
        ErroLeitura: arquivo inexistente, formato não suportado, campo identificador ausente.
        ErroCRS: CRS ausente, não projetado em metros ou divergente entre raster e talhões.
        ErroContrato: talhão não-polígono, vazio ou inválido, id duplicado,
            bandas de cfg.bandas_rgb inexistentes no raster."""
    ...

def verificar_crs(camadas: dict[str, CRS]) -> None:
    """Compara por equivalência (CRS.equals), não por texto. Usado também pela comparação.
    Raises: ErroCRS listando todas as camadas e quais divergem do primeiro item. Não reprojeta."""
    ...
```

### 6.2 indice_binarizacao (src/deteccao_linhas/indice_binarizacao.py)

```python
class FonteIndice:
    """Leitor preguiçoso do índice de vegetação; lê o GeoTIFF por janelas."""
    crs: CRS
    resolucao_nativa_m: float
    def ler_janela(self, bounds: tuple[float, float, float, float],
                   resolucao_m: float | None = None) -> JanelaRaster:
        """Índice float32 na janela. resolucao_m maior que a nativa reduz por média de área;
        None usa cfg.resolucao_trabalho_m. validade False em nodata.
        Raises: ErroContrato se bounds não intersecta o raster; ErroConfig se resolucao_m < nativa."""
        ...
    def fechar(self) -> None: ...

def abrir_fonte_indice(caminho_ortomosaico: Path, cfg: Config) -> FonteIndice:
    """Prepara o cálculo do índice de cfg.indice sob demanda por janela."""
    ...

def calcular_indice(bandas: np.ndarray, cfg: Config) -> np.ndarray:
    """Função pura. bandas (3, h, w) -> (h, w) float32 com exg (variante cfg.variante_exg) ou vari.
    Divisão por zero vira NaN."""
    ...

def recortar_talhao(talhao: Talhao, cfg: Config) -> AreaTalhao:
    """Buffer interno negativo (cfg.buffer_interno_m) e bounds.
    Raises: ErroContrato se a área útil ficar vazia."""
    ...

class FonteBinaria:
    """Leitor preguiçoso do raster binário (True = vegetação) de um talhão."""
    def ler_janela(self, bounds: tuple[float, float, float, float],
                   resolucao_m: float | None = None) -> JanelaRaster:
        """valores bool (ou float32 do índice se cfg.perfil_sobre == 'indice');
        validade False fora da área útil e em nodata."""
        ...

def calcular_limiar_otsu(fonte: FonteIndice, area: AreaTalhao, cfg: Config) -> float:
    """Otsu por talhão. Histograma acumulado por janelas (duas passagens: faixa e histograma).
    Raises: ErroDeteccao se a área útil não tiver pixels válidos."""
    ...

def abrir_fonte_binaria(fonte: FonteIndice, area: AreaTalhao, limiar: float, cfg: Config) -> FonteBinaria:
    """Binariza por janela: índice >= limiar é vegetação."""
    ...
```

### 6.3 orientacao (src/deteccao_linhas/orientacao.py)

Segue Ferreira et al. (2025) na ideia de projeção por rotação com Savitzky-Golay. O critério exato de escolha do ângulo é decisão de implementação a registrar e conferir contra o método do artigo.

```python
def dividir_em_regioes(area: AreaTalhao, cfg: Config) -> list[Regiao]:
    """Divide a área útil em regiões de lado cfg.regiao_m, recortadas pelo polígono útil.
    Regiões com área menor que cfg.area_minima_regiao_m2 são marcadas para herdar direção.
    Raises: ErroContrato se não restar região."""
    ...

def estimar_direcao_regiao(fonte: FonteBinaria, regiao: Regiao, cfg: Config) -> DirecaoFileiras:
    """Projeção por rotação na janela da região, em dois passos (grosso e fino); perfil de
    projeção suavizado com Savitzky-Golay. Devolve ângulo módulo 180 e confiança.
    O vetor sai com sentido provisório (norte positivo); o alinhamento a u_ref é feito em estimar_direcoes.
    Raises: ErroDeteccao se a região não tiver pixels válidos suficientes."""
    ...

def estimar_direcoes(
    fonte: FonteBinaria, regioes: list[Regiao], cfg: Config,
) -> tuple[list[Regiao], tuple[float, float]]:
    """Estima a direção de cada região, define u_ref (mediana circular, módulo 180, ponderada
    por área e confiança) e alinha o sentido de cada região a u_ref. Região sem estimativa confiável,
    ou com ângulo a mais de cfg.desvio_angular_max_graus da mediana das vizinhas, herda a direção
    das vizinhas e fica com herdada=True.
    Raises: ErroDeteccao se nenhuma região tiver direção estimável."""
    ...
```

### 6.4 perfil_lateral (src/deteccao_linhas/perfil_lateral.py)

```python
def gerar_blocos(regioes: list[Regiao], u_ref: tuple[float, float], c_ref: tuple[float, float],
                 cfg: Config) -> list[Bloco]:
    """Blocos retangulares orientados por região: comprimento cfg.comprimento_bloco_m, avanço
    cfg.passo_bloco_m, extensão lateral cobrindo a região. Ordenados por s_global_m crescente."""
    ...

def calcular_perfil(fonte: FonteBinaria, bloco: Bloco, cfg: Config) -> PerfilLateral:
    """Integra a vegetação ao longo de bloco.u em bins laterais de cfg.bin_lateral_m (H1).
    Lê só a janela do bloco. Pixels inválidos não entram na média; cobertura registra a fração válida.
    Calcula também a coerência longitudinal por bin (subtrechos de cfg.subtrecho_m)."""
    ...
```

### 6.5 pente (src/deteccao_linhas/pente.py)

```python
def ajustar_fase(perfil: PerfilLateral, cfg: Config) -> list[float]:
    """Fase local do pente (H2) em janelas deslizantes de cfg.dentes_por_janela_fase dentes,
    com periodicidade cfg.espacamento_fileiras_ref_m. Fases diferentes entre janelas vizinhas são
    aceitas até cfg.tolerancia_espacamento_m: é assim que o salto entre passadas é absorvido.
    Devolve uma fase por janela. Perfil sem pico acima de cfg.proeminencia_min devolve lista vazia."""
    ...

def localizar_dentes(perfil: PerfilLateral, fases: list[float], cfg: Config) -> tuple[PosicaoFileira, ...]:
    """Em cada dente do pente, procura o centro da faixa em +-cfg.semijanela_dente_m e mede largura,
    proeminência, coerência e ajuste ao pente. Dente sem pico: sem posição (nunca preenche).
    Marca salto=True onde o espaçamento à vizinha foge de cfg.espacamento_fileiras_ref_m
    por mais de cfg.tolerancia_espacamento_m."""
    ...

def ajustar_bloco(perfil: PerfilLateral, cfg: Config) -> ResultadoPente:
    """Encadeia ajustar_fase e localizar_dentes; converte t local em (x, y)."""
    ...
```

### 6.6 rastreamento (src/deteccao_linhas/rastreamento.py)

```python
def rastrear(resultados: list[ResultadoPente], cfg: Config) -> list[Trilha]:
    """Liga posições de blocos consecutivos (em ordem de s_global_m) em fileiras contínuas.
    A ligação é feita no espaço do mapa: cada trilha ativa é projetada ao bloco seguinte ao longo da
    direção local, e a associação é um-para-um, com limite cfg.tolerancia_ligacao_m na distância lateral.
    Posição sem trilha inicia uma nova. Trilha sem posição por até cfg.max_blocos_falha blocos segue
    projetada; se reconfirmada depois, os blocos intermediários viram status 'interpolado'; se não,
    é encerrada no último bloco com detecção (nada projetado é mantido).
    Trilha mais curta que cfg.comprimento_min_fileira_m é descartada e contada no resumo.
    Não numera."""
    ...
```

### 6.7 qualidade (src/deteccao_linhas/qualidade.py)

```python
def calcular_confianca(pos: PosicaoFileira, cfg: Config) -> float:
    """Combina contraste (proeminência), coerência longitudinal, largura frente a
    [largura_faixa_min_m - tol, largura_faixa_max_m + tol] e ajuste ao pente, com cfg.pesos_confianca.
    Fórmula exata é hipótese (H5), a fixar na implementação e documentar."""
    ...

def classificar_ponto(confianca: float, cfg: Config) -> Status:
    """'duvidoso' se confianca < cfg.limiar_confianca; senão 'detectado'. 'interpolado' vem do rastreamento."""
    ...

def marcar_saltos_laterais(trilha: Trilha, cfg: Config) -> Trilha:
    """Marca 'duvidoso' o ponto cuja posição lateral difere da mediana local (cfg.janela_mediana),
    após remover a tendência, por mais de cfg.limite_variacao_m. A posição não é alterada."""
    ...

def avaliar_trilha(trilha: Trilha, talhao: str, cfg: Config) -> FileiraAvaliada:
    """Monta geometria, comprimento_m, confianca_media e frac_duvidosa."""
    ...

def avaliar_trilhas(trilhas: list[Trilha], talhao: str, cfg: Config) -> list[FileiraAvaliada]:
    """Aplica as regras a todas as trilhas do talhão."""
    ...
```

### 6.8 saida (src/deteccao_linhas/saida.py)

```python
def numerar_fileiras(avaliadas: list[FileiraAvaliada], u_ref: tuple[float, float],
                     c_ref: tuple[float, float]) -> list[Fileira]:
    """Aplica a convenção da seção 1: ordem crescente da mediana de t_g; id 'talhao-F0001'."""
    ...

def gravar_geopackage(fileiras: list[Fileira], crs: CRS, caminho_saida: Path) -> None:
    """Grava as camadas abaixo no CRS da entrada.
    Raises: ErroLeitura (caminho não gravável); ErroContrato (status fora do conjunto)."""
    ...
```

Camada `fileiras` (linha):

| Atributo | Tipo | Descrição |
|---|---|---|
| id_fileira | texto | `talhao-F0001`, convenção da seção 1 |
| talhao | texto | Identificador do talhão |
| comprimento_m | real | Comprimento da linha |
| confianca_media | real | Média de `confianca` dos pontos, 0 a 1 |
| frac_duvidosa | real | Fração dos pontos com status `duvidoso` |

Camada `trechos` (ponto, um por bloco e fileira):

| Atributo | Tipo | Descrição |
|---|---|---|
| id_fileira | texto | Fileira à qual o ponto pertence |
| posicao_m | real | Distância ao longo da fileira |
| status | texto | `detectado`, `interpolado` ou `duvidoso` |
| confianca | real | 0 a 1 |

### 6.9 comparacao (src/deteccao_linhas/comparacao.py)

Independente da detecção: lê o GeoPackage de saída e uma camada de referência. Importa só `entrada.verificar_crs` e `tipos`.

```python
@dataclass(frozen=True)
class EstatisticaDistancia:
    n: int
    media_abs_m: float | None
    mediana_abs_m: float | None
    p95_abs_m: float | None
    vies_m: float | None             # média com sinal; + quando a fileira detectada está à esquerda da referência, no sentido da fileira

@dataclass(frozen=True)
class RelatorioComparacao:
    aviso: str                       # fixo: "Referência secundária, não é RTK; não mede acurácia."
    n_trechos: int
    taxa_pareamento: float           # trechos com referência a menos de distancia_max_pareamento_m
    cobertura_referencia: float      # fração do comprimento da referência com fileira detectada pareada
    global_: EstatisticaDistancia    # status em cfg.usar_status
    por_status: dict[str, EstatisticaDistancia]
    por_fileira: dict[str, EstatisticaDistancia]

def carregar_referencia(caminho: Path, crs_esperado: CRS, cfg: ConfigComparacao) -> tuple[LineString, ...]:
    """Raises: ErroLeitura; ErroCRS (divergente do CRS das fileiras, sem reprojetar);
    ErroContrato (geometria não-linha, vazia ou inválida)."""
    ...

def distancia_lateral(ponto_x: float, ponto_y: float, direcao: tuple[float, float],
                      referencia: tuple[LineString, ...], cfg: ConfigComparacao) -> float | None:
    """Distância com sinal, medida na normal à esquerda de `direcao`, até a linha de referência mais
    próxima dentro de cfg.distancia_max_pareamento_m. None se não houver (trecho não pareado)."""
    ...

def comparar(caminho_fileiras: Path, caminho_referencia: Path, cfg: ConfigComparacao) -> RelatorioComparacao:
    """Mede, por trecho detectado, a distância lateral à referência e agrega. Não altera nenhuma
    camada. Raises: ErroLeitura, ErroCRS, ErroContrato; ErroDeteccao se a camada de fileiras estiver vazia."""
    ...

def gravar_diferencas(caminho_fileiras: Path, relatorio: RelatorioComparacao, caminho_saida: Path) -> None:
    """Opcional. Grava camada de pontos com a distância lateral por trecho, para inspeção visual."""
    ...
```

### 6.10 cli (src/deteccao_linhas/cli.py e __main__.py)

```
python -m deteccao_linhas detectar --ortomosaico X --talhoes Y --saida W [--config C]
python -m deteccao_linhas comparar --fileiras F --referencia R [--config C] [--relatorio J] [--saida-diferencas D]
```

```python
def main(argv: list[str] | None = None) -> int:
    """Subcomandos 'detectar' e 'comparar'. --config é opcional (padrões sem ele).
    Imprime progresso por talhão e resumo. Códigos de saída: 0 sucesso; 2 erro de contrato
    (ErroDeteccaoLinhas, mensagem em português no stderr); 1 erro inesperado."""
    ...

def executar_deteccao(caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_saida: Path,
                      cfg: Config) -> list[ResumoDeteccao]:
    """Orquestra o fluxo da seção 5 talhão a talhão. Sem lógica de geometria própria.
    Ponto de integração futuro do plugin QGIS."""
    ...

def executar_comparacao(caminho_fileiras: Path, caminho_referencia: Path,
                        cfg: ConfigComparacao) -> RelatorioComparacao:
    """Chama comparacao.comparar. A detecção nunca é chamada daqui."""
    ...
```

## 7. Testes (tests/deteccao_linhas/)

Um arquivo por módulo. Dados sintéticos: fileiras retas com vãos, erva fora da linha, direção diferente por região, salto de espaçamento entre passadas. Provam o funcionamento do algoritmo, não a acurácia. Um teste confere que a detecção não lê nenhuma camada de linhas.

## 8. Pontos a decidir

1. Curvas e terraços. A versão varia a direção por região, com fileira reta dentro do bloco. Fileira curva dentro do bloco não é modelada e tende a ficar duvidosa. Aceitar essa limitação na primeira versão?
2. Comprimento do bloco (10 m, hipótese central H1). Bloco longo ajuda na descontinuidade e dilui variação rápida de posição. Fixar no piloto ou expor também um modo de dois comprimentos?
3. Perfil sobre o binário ou sobre o índice contínuo (`perfil_sobre`). O binário segue o artigo na orientação; para posição lateral não há fonte.
4. Fileira cortada por falha longa vira duas fileiras com ids distintos. Reunir depois por continuidade?
5. Numeração em curvas: a ordem por `t_g` pode trocar. Basta como chave ou precisa de numeração por vizinhança?
6. Ponto com status `duvidoso` entra na geometria da fileira (posição medida, marcada). Alternativa: tirar da linha e quebrar a fileira.
7. Duplicar o código comum de entrada e configuração com `linhas_plantio` ou extrair depois um núcleo compartilhado. Esta versão duplica, para manter o pacote independente.
8. `trechos` como ponto por bloco (adotado) ou segmento por bloco.
9. Pareamento na comparação: um único limite de distância (0,50 m) e a linha mais próxima. Há risco de parear com a fileira vizinha se as linhas recebidas estiverem deslocadas perto de 0,75 m; o relatório mostra o viés para revelar isso. Aceitar?
10. Nome do atributo de confiança da camada `fileiras`: `confianca_media` (adotado).
