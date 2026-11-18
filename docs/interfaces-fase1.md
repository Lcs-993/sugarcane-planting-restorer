# Interfaces da fase 1

Documento da Etapa A. Contém só interfaces: assinaturas, entradas, saídas, tipos e erros. Nenhum corpo de implementação (`...`). Segue docs/escopo.md e docs/arquitetura.md; vale a regra de evidência do projeto: parâmetro sem fonte lida é hipótese configurável, nunca fato.

Dentro da fase: entrada, preprocessamento, segmentacao, deteccao, desvio, qualidade (básica), reconstrucao, saida e linha de comando. Fora da fase: mascaras, falhas, mds_opcional e qgis_plugin (não aparecem aqui e não serão criados).

## 1. Convenções gerais

- Todas as camadas e o raster no mesmo sistema de coordenadas projetado, em metros. O motor não reprojeta; as saídas herdam o CRS da entrada.
- Ortomosaico lido por janelas (rasterio), nunca inteiro na memória. Nenhuma função recebe ou devolve o raster inteiro.
- Processamento talhão a talhão.
- Distâncias em metros. `estacao_m` é a distância ao longo da linha projetada, a partir do primeiro vértice, no sentido de digitalização.
- Coordenada transversal `t` (metros, relativa à linha projetada): positiva à esquerda, negativa à direita, no sentido de digitalização. A fileira esquerda projetada fica em `t = +0,75`; a direita em `t = -0,75`.
- **Convenção do sinal de `desvio_m`: positivo quando o eixo real do par está à esquerda da linha projetada, no sentido de digitalização.** Logo `desvio_m = (t_esq + t_dir) / 2`, com `t_esq` e `t_dir` os centros detectados das duas fileiras.
- Trecho duvidoso ou interpolado é sempre marcado em `status`; nada é corrigido em silêncio.
- Valor numérico sem fonte lida é hipótese configurável (ver seção 4).
- Testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo. A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.

## 2. Contrato de dados

### 2.1 Entradas

| Entrada | Formato | Requisitos |
|---|---|---|
| Ortomosaico | GeoTIFF, bandas RGB, 3 cm por pixel | Índice configurável: `exg` (padrão), `vari` ou `ndvi`. `ndvi` exige que a configuração indique a banda do infravermelho próximo. |
| Talhões | GeoPackage ou shapefile, polígonos | Campo identificador (nome em `Config.campo_id_talhao`). |
| Linhas de piloto projetadas | GeoPackage ou shapefile, linhas, uma por passada | Campo identificador (nome em `Config.campo_id_passada`). DXF fica para fase posterior. |

Camadas e raster com CRS diferentes: parar com `ErroCRS`, listando cada camada e seu CRS e indicando quais divergem. Sem reprojeção silenciosa. Sem comentário sobre qualidade ou georreferenciamento do ortomosaico.

### 2.2 Saídas (um GeoPackage)

Camada `linhas_corrigidas`: uma linha por passada, mesmo CRS da entrada.

| Atributo | Tipo | Descrição |
|---|---|---|
| id_passada | texto | Identificador da passada |
| talhao | texto | Identificador do talhão |
| n_estacoes | inteiro | Total de estações |
| frac_duvidosa | real | Fração de estações com status `duvidoso` |
| frac_interpolada | real | Fração de estações com status `interpolado` |
| revisao_manual | booleano | Verdadeiro se `frac_duvidosa` passar do limiar configurável |

Camada `estacoes`: um ponto por estação.

| Atributo | Tipo | Descrição |
|---|---|---|
| id_passada | texto | Identificador da passada |
| talhao | texto | Identificador do talhão |
| estacao_m | real | Distância ao longo da linha projetada |
| desvio_m | real, anulável | Desvio lateral aplicado à linha corrigida naquela estação, com a convenção de sinal da seção 1; nulo quando não há valor |
| status | texto | `detectado`, `estimado` (só uma fileira detectada), `interpolado` ou `duvidoso` |
| confianca | real | 0 a 1 |

Significado dos status:
- `detectado`: as duas fileiras foram encontradas e passaram nas regras de qualidade.
- `estimado`: só uma fileira foi encontrada; o eixo vem dela com o offset de 0,75 m.
- `interpolado`: sem detecção utilizável, mas com estação boa nas duas extremidades do trecho; `desvio_m` vem da interpolação.
- `duvidoso`: reprovada nas regras de qualidade, ou sem detecção e sem estação boa nas duas extremidades. `desvio_m` é o valor suavizado do perfil se o trecho for interpolável, senão nulo.

### 2.3 Erros

```python
class ErroLinhasPlantio(Exception): ...        # base
class ErroConfig(ErroLinhasPlantio): ...       # parâmetro ausente, fora de faixa ou desconhecido
class ErroLeitura(ErroLinhasPlantio): ...      # arquivo inexistente, formato ou campo identificador ausente
class ErroCRS(ErroLinhasPlantio): ...          # CRS divergente, ausente ou não projetado em metros
class ErroContrato(ErroLinhasPlantio): ...     # geometria de tipo errado, id duplicado, linha fora de talhão, banda inexistente
```

Mensagem de `ErroCRS` (formato): `CRS divergente: ortomosaico=EPSG:31983; talhoes=EPSG:4674; linhas=EPSG:31983. Divergem do ortomosaico: talhoes. Reprojete as camadas antes de rodar.`

## 3. Configuração e tipos compartilhados

### 3.1 src/linhas_plantio/config.py

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

@dataclass(frozen=True)
class Config:
    # Índice de vegetação
    indice: Literal["exg", "vari", "ndvi"] = "exg"
    bandas_rgb: tuple[int, int, int] = (1, 2, 3)   # numeração do rasterio, base 1
    banda_nir: int | None = None                   # obrigatória se indice == "ndvi"

    # Estações e busca (hipóteses de partida do projeto)
    espacamento_estacoes_m: float = 10.0
    semijanela_busca_m: float = 0.50

    # Regras geométricas (premissas do projeto como referência; tolerâncias são hipóteses)
    espacamento_gemeas_ref_m: float = 1.50
    tolerancia_espacamento_gemeas_m: float = 0.15
    largura_faixa_min_m: float = 0.45
    largura_faixa_max_m: float = 0.50
    tolerancia_largura_m: float = 0.10

    # Suavização e ruído
    janela_mediana: int = 3                        # em estações, ímpar
    limite_variacao_m: float = 0.30                # entre estações vizinhas
    fator_spline: float = 0.0                      # 0 = spline interpolador; > 0 suaviza

    # Talhão e perfil
    buffer_interno_m: float = 5.0
    comprimento_amostra_m: float = 1.0             # trecho longitudinal médio em cada ponto do perfil
    fracao_duvidosa_revisao: float = 0.30

    # Campos identificadores
    campo_id_talhao: str = "id"
    campo_id_passada: str = "id"

def carregar_config(caminho: Path | None) -> Config:
    """Lê YAML e devolve Config. None devolve os padrões.
    Raises: ErroConfig (chave desconhecida, tipo errado, valor fora de faixa,
    ndvi sem banda_nir, janela_mediana par)."""
    ...
```

O arquivo `config.yaml` de exemplo (raiz do repositório) repete esses campos, com cada valor comentado como hipótese.

### 3.2 src/linhas_plantio/tipos.py (dataclasses compartilhadas)

```python
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from affine import Affine
from pyproj import CRS
from shapely.geometry import LineString, Polygon, MultiPolygon

@dataclass(frozen=True)
class Talhao:
    id: str
    poligono: Polygon | MultiPolygon

@dataclass(frozen=True)
class Passada:
    id_passada: str
    talhao: str                      # id do talhão que contém a linha
    geometria: LineString            # sentido de digitalização preservado

@dataclass(frozen=True)
class DadosEntrada:
    caminho_ortomosaico: Path
    crs: CRS
    talhoes: tuple[Talhao, ...]
    passadas: tuple[Passada, ...]

@dataclass(frozen=True)
class JanelaRaster:
    valores: np.ndarray              # 2D; float32 (índice) ou bool (binário)
    validade: np.ndarray             # 2D bool; False onde não há dado (nodata) ou fora do polígono útil
    transform: Affine

@dataclass(frozen=True)
class AreaTalhao:
    talhao: Talhao
    poligono_util: Polygon | MultiPolygon    # talhão com buffer interno negativo
    bounds: tuple[float, float, float, float]

@dataclass(frozen=True)
class PerfilTransversal:
    t_m: np.ndarray                  # coordenada transversal, positiva à esquerda
    valores: np.ndarray              # fração de vegetação (0 a 1) média em comprimento_amostra_m; NaN se sem dado

@dataclass(frozen=True)
class DeteccaoEstacao:
    id_passada: str
    estacao_m: float
    x: float
    y: float
    normal_esq: tuple[float, float]  # vetor unitário à esquerda da linha projetada
    t_esq_m: float | None            # centro da fileira esquerda; None se não encontrado
    t_dir_m: float | None
    largura_esq_m: float | None
    largura_dir_m: float | None
    confianca_esq: float             # 0 a 1
    confianca_dir: float

@dataclass(frozen=True)
class EstacaoDesvio:
    id_passada: str
    talhao: str
    estacao_m: float
    x: float
    y: float
    normal_esq: tuple[float, float]
    desvio_m: float | None           # bruto; None se nenhuma fileira detectada
    espacamento_gemeas_m: float | None
    largura_esq_m: float | None
    largura_dir_m: float | None
    status: str                      # detectado | estimado | duvidoso (interpolado só após reconstrucao)
    confianca: float                 # 0 a 1

@dataclass(frozen=True)
class ResultadoPassada:
    passada: Passada
    estacoes: tuple[EstacaoDesvio, ...]     # com desvio_m e status finais
    linha_corrigida: LineString
    frac_duvidosa: float
    frac_interpolada: float
    revisao_manual: bool
```

## 4. Parâmetros hipótese

Nenhum destes tem fonte lida. São parâmetros configuráveis, a definir no piloto. As premissas geométricas (1,50 m, 45 a 50 cm, 0,75 m) são do projeto e não são hipótese.

| Parâmetro | Valor inicial | Origem |
|---|---|---|
| espacamento_estacoes_m | 10,0 | Hipótese de partida do projeto (5 a 10 m) |
| semijanela_busca_m | 0,50 | Hipótese de partida do projeto |
| tolerancia_espacamento_gemeas_m | 0,15 | Hipótese |
| tolerancia_largura_m | 0,10 | Hipótese |
| janela_mediana | 3 estações | Hipótese |
| limite_variacao_m | 0,30 | Hipótese; depende do espaçamento entre estações |
| buffer_interno_m | 5,0 | Hipótese |
| indice | exg | Escolha de projeto, não validada |
| fator_spline | 0,0 | Hipótese, parâmetro adicional |
| comprimento_amostra_m | 1,0 | Hipótese, parâmetro adicional |
| fracao_duvidosa_revisao | 0,30 | Hipótese, parâmetro adicional |

## 5. Fluxo de dados

```
entrada.carregar_entrada            -> DadosEntrada (valida CRS, ids e linha em talhão)
por talhão:
  preprocessamento.abrir_fonte_indice + recortar_talhao -> FonteIndice, AreaTalhao
  segmentacao.calcular_limiar_otsu + abrir_fonte_binaria -> FonteBinaria
  por passada do talhão:
    deteccao.detectar_passada       -> list[DeteccaoEstacao]
    desvio.calcular_desvios         -> list[EstacaoDesvio]
    qualidade.avaliar_passada       -> list[EstacaoDesvio] com status e confiança
    reconstrucao.reconstruir_passada -> ResultadoPassada
saida.gravar_geopackage             -> GeoPackage (linhas_corrigidas, estacoes)
```

## 6. Módulos

### 6.1 entrada (src/linhas_plantio/entrada.py)

```python
def carregar_entrada(
    caminho_ortomosaico: Path,
    caminho_talhoes: Path,
    caminho_linhas: Path,
    cfg: Config,
) -> DadosEntrada:
    """Lê raster (só metadados), talhões e linhas e valida o contrato.
    Raises:
        ErroLeitura: arquivo inexistente, formato não suportado, campo identificador ausente.
        ErroCRS: CRS ausente, não projetado em metros ou divergente entre raster, talhões e linhas.
        ErroContrato: geometria de tipo errado (linha não-LineString, talhão não-polígono),
            geometria vazia ou inválida, id duplicado, banda indicada em Config inexistente
            no raster, linha fora de qualquer talhão."""
    ...

def verificar_crs(camadas: dict[str, CRS]) -> None:
    """Compara os CRS (ex.: {"ortomosaico": ..., "talhoes": ..., "linhas": ...}).
    Raises: ErroCRS listando todas as camadas e quais divergem. Não reprojeta."""
    ...

def atribuir_talhao(linha: LineString, talhoes: tuple[Talhao, ...]) -> str:
    """Devolve o id do talhão que contém a linha.
    Raises: ErroContrato se a linha não cair em nenhum talhão."""
    ...
```

### 6.2 preprocessamento (src/linhas_plantio/preprocessamento.py)

```python
class FonteIndice:
    """Leitor preguiçoso do índice de vegetação; lê o GeoTIFF por janelas."""
    crs: CRS
    resolucao_m: float
    def ler_janela(self, bounds: tuple[float, float, float, float]) -> JanelaRaster:
        """Lê a janela cobrindo bounds e devolve o índice (float32).
        validade é False em nodata. Raises: ErroContrato se bounds não intersecta o raster."""
        ...
    def fechar(self) -> None: ...

def abrir_fonte_indice(caminho_ortomosaico: Path, cfg: Config) -> FonteIndice:
    """Abre o raster e prepara o cálculo do índice de cfg.indice sob demanda por janela.
    Raises: ErroContrato (banda indicada inexistente; ndvi sem banda_nir)."""
    ...

def recortar_talhao(talhao: Talhao, cfg: Config) -> AreaTalhao:
    """Aplica buffer interno negativo (cfg.buffer_interno_m) e calcula bounds.
    Raises: ErroContrato se o polígono útil ficar vazio."""
    ...

def calcular_indice(bandas: np.ndarray, cfg: Config) -> np.ndarray:
    """Função pura. bandas: (n, h, w). Devolve (h, w) float32 com o índice de cfg.indice
    (exg, vari ou ndvi). Divisão por zero vira NaN."""
    ...
```

### 6.3 segmentacao (src/linhas_plantio/segmentacao.py)

```python
class FonteBinaria:
    """Leitor preguiçoso do raster binário (True = cana) de um talhão."""
    def ler_janela(self, bounds: tuple[float, float, float, float]) -> JanelaRaster:
        """valores bool; validade False fora do polígono útil e em nodata."""
        ...

def calcular_limiar_otsu(fonte: FonteIndice, area: AreaTalhao, n_bins: int = 256) -> float:
    """Otsu calculado em cada talhão. O histograma é acumulado lendo a área útil por janelas
    (duas passagens: faixa de valores e histograma); o raster do talhão nunca fica inteiro na memória.
    Raises: ErroContrato se a área útil não tiver pixels válidos."""
    ...

def abrir_fonte_binaria(fonte: FonteIndice, area: AreaTalhao, limiar: float) -> FonteBinaria:
    """Binariza por janela: índice >= limiar é cana."""
    ...
```

### 6.4 deteccao (src/linhas_plantio/deteccao.py)

Segue a skill perfil-transversal: a linha projetada é o guia; o centro de cada faixa é procurado numa janela estreita ao redor da posição projetada (±0,75 m), sem detectar fileiras do zero.

```python
def gerar_estacoes(linha: LineString, espacamento_m: float) -> np.ndarray:
    """Distâncias ao longo da linha: 0, e, 2e, ... e a extremidade final sempre incluída."""
    ...

def amostrar_perfil(
    fonte: FonteBinaria, x: float, y: float, normal_esq: tuple[float, float],
    tangente: tuple[float, float], cfg: Config,
) -> PerfilTransversal:
    """Perfil perpendicular à linha cobrindo as duas fileiras projetadas com a semijanela
    de busca e a meia-largura da faixa. Cada ponto do perfil é a média da vegetação em
    cfg.comprimento_amostra_m ao longo da linha. Lê só a janela necessária."""
    ...

def localizar_centros(perfil: PerfilTransversal, cfg: Config) -> tuple[
    tuple[float | None, float | None, float],   # fileira esquerda: centro_t, largura, confianca
    tuple[float | None, float | None, float],   # fileira direita
]:
    """Procura o centro de cada faixa em [+0,75 ± semijanela] e [-0,75 ± semijanela].
    Sem pico confiável devolve (None, None, 0.0); nunca preenche."""
    ...

def detectar_passada(passada: Passada, fonte: FonteBinaria, cfg: Config) -> list[DeteccaoEstacao]:
    """Uma DeteccaoEstacao por estação da passada."""
    ...
```

### 6.5 desvio (src/linhas_plantio/desvio.py)

Segue a skill ajuste-pente-gemeas.

```python
def calcular_desvio_estacao(det: DeteccaoEstacao, talhao: str, cfg: Config) -> EstacaoDesvio:
    """Duas fileiras: desvio_m = (t_esq + t_dir)/2; espacamento_gemeas_m = t_esq - t_dir; status 'detectado'.
    Uma fileira: desvio_m = t_esq - 0,75 (ou t_dir + 0,75), status 'estimado'.
    Nenhuma: desvio_m None, status 'duvidoso'.
    Não aplica tolerâncias (isso é da qualidade)."""
    ...

def calcular_desvios(passada: Passada, deteccoes: list[DeteccaoEstacao], cfg: Config) -> list[EstacaoDesvio]:
    """Aplica calcular_desvio_estacao a todas as estações da passada."""
    ...
```

### 6.6 qualidade, regras básicas (src/linhas_plantio/qualidade.py)

```python
def avaliar_geometria(est: EstacaoDesvio, cfg: Config) -> EstacaoDesvio:
    """Marca 'duvidoso' se |espacamento_gemeas_m - 1,50| > tolerancia_espacamento_gemeas_m,
    ou se a largura de alguma faixa estiver fora de [0,45 - tol, 0,50 + tol]."""
    ...

def marcar_saltos(estacoes: list[EstacaoDesvio], cfg: Config) -> list[EstacaoDesvio]:
    """Marca 'duvidoso' a estação cujo desvio difere da mediana local dos vizinhos
    por mais de limite_variacao_m (ruído de detecção; o trator não muda de trajetória bruscamente)."""
    ...

def calcular_confianca(est: EstacaoDesvio, cfg: Config) -> float:
    """Confiança de 0 a 1 combinando as confianças das fileiras, o status e a proximidade
    das tolerâncias. Fórmula exata é hipótese, a fixar na implementação e documentar."""
    ...

def avaliar_passada(estacoes: list[EstacaoDesvio], cfg: Config) -> list[EstacaoDesvio]:
    """Encadeia as três funções acima e devolve as estações com status e confiança finais de detecção."""
    ...
```

Fora desta fase: espaçamento entre fileiras de passadas vizinhas (sobreposição e vão), listado em docs/arquitetura.md; exige comparar passadas e fica para depois.

### 6.7 reconstrucao (src/linhas_plantio/reconstrucao.py)

Segue a skill suavizacao-deriva.

```python
def montar_perfil(estacoes: list[EstacaoDesvio]) -> tuple[np.ndarray, np.ndarray]:
    """(estacao_m, desvio_m) só das estações boas (detectado ou estimado, com desvio_m)."""
    ...

def suavizar_perfil(s: np.ndarray, d: np.ndarray, cfg: Config) -> Callable[[np.ndarray], np.ndarray]:
    """Filtro de mediana (cfg.janela_mediana) seguido de spline (cfg.fator_spline).
    Devolve a função desvio(estacao_m). Raises: ErroContrato se houver menos de 2 estações boas."""
    ...

def interpolar_trechos(
    estacoes: list[EstacaoDesvio], perfil: Callable[[np.ndarray], np.ndarray],
) -> list[EstacaoDesvio]:
    """Estações sem detecção utilizável, com estação boa nas duas extremidades, recebem
    desvio_m do perfil e status 'interpolado'. Estações 'duvidosas' por qualidade mantêm
    status 'duvidoso' (com desvio_m do perfil se interpolável). Sem estação boa nas duas
    extremidades: desvio_m None, status 'duvidoso'. As estações boas recebem o valor suavizado."""
    ...

def reconstruir_linha(passada: Passada, estacoes: list[EstacaoDesvio]) -> LineString:
    """Desloca cada vértice da linha projetada (e cada estação) pela normal esquerda com o
    desvio interpolado em estacao_m. Onde desvio_m é None o deslocamento é 0 (linha projetada
    mantida) e o trecho fica marcado duvidoso."""
    ...

def reconstruir_passada(passada: Passada, estacoes: list[EstacaoDesvio], cfg: Config) -> ResultadoPassada:
    """Calcula frac_duvidosa, frac_interpolada e revisao_manual (frac_duvidosa > fracao_duvidosa_revisao)."""
    ...
```

### 6.8 saida (src/linhas_plantio/saida.py)

```python
def gravar_geopackage(resultados: list[ResultadoPassada], crs: CRS, caminho_saida: Path) -> None:
    """Grava as camadas linhas_corrigidas e estacoes (seção 2.2) no CRS da entrada.
    Geometria da estação: ponto da linha projetada deslocado por desvio_m (na posição projetada se nulo).
    Raises: ErroLeitura se o caminho não for gravável; ErroContrato se status fora do conjunto permitido."""
    ...
```

## 7. Linha de comando

```
python -m linhas_plantio corrigir --ortomosaico X --talhoes Y --linhas Z --saida W --config C
```

Arquivos: `src/linhas_plantio/__main__.py` (chama `cli.main`) e `src/linhas_plantio/cli.py`.

```python
def main(argv: list[str] | None = None) -> int:
    """Subcomando 'corrigir'. --config é opcional (sem ele, usa os padrões). Imprime progresso por talhão
    e o resumo final (passadas, estações por status, passadas para revisão manual).
    Códigos de saída: 0 sucesso; 2 erro de contrato (ErroLinhasPlantio, mensagem em português no stderr);
    1 erro inesperado."""
    ...

def executar_correcao(
    caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_linhas: Path,
    caminho_saida: Path, cfg: Config,
) -> list[ResultadoPassada]:
    """Orquestra o fluxo da seção 5 talhão a talhão. Sem lógica de geometria própria."""
    ...
```

## 8. Pontos a decidir

1. Arquivos adicionais além dos módulos de docs/arquitetura.md: `config.py`, `tipos.py`, `cli.py`, `__main__.py` e `config.yaml` (raiz). Aprovar?
2. `desvio_m` na saída é o valor aplicado à linha (suavizado ou interpolado), não a medida bruta. Quer também `desvio_bruto_m`? Isso ajudaria a validação, mas amplia o contrato.
3. Atributos extras de `linhas_corrigidas` (n_estacoes, frac_duvidosa, frac_interpolada, revisao_manual) e o limiar de 0,30 para revisão manual: aprovar?
4. Linha que cruza mais de um talhão ou só parcialmente contida: a interface atual exige linha totalmente contida num talhão e levanta `ErroContrato`. Alternativa: atribuir ao talhão com maior comprimento interno e avisar.
5. Estação sem valor utilizável e sem estação boa nas duas pontas mantém a linha projetada (deslocamento 0), marcada `duvidoso`. Confirmar.
6. `limite_variacao_m` é absoluto entre estações vizinhas; com espaçamento de 10 m uma deriva real rápida pode ser marcada como ruído. Alternativa: limite por metro percorrido.
7. Posição do ponto da estação: linha projetada deslocada por `desvio_m`. Alternativa: sempre na linha projetada.
8. Pixels em nodata são tratados como sem dado (validade falsa) e geram estação sem detecção; sem comentário sobre a qualidade do mosaico.
9. Comparação de CRS por equivalência (pyproj `CRS.equals`), não por texto, para não acusar divergência entre grafias do mesmo CRS.

## 9. Decisões aprovadas

O usuário aprovou as interfaces sem pedir mudanças. Valem as propostas da seção 8:

- Arquivos adicionais criados: `tipos.py` (inclui os erros da seção 2.3), `cli.py`, `__main__.py` e `config.yaml` na raiz.
- `desvio_m` na saída é o valor aplicado (suavizado ou interpolado); sem campo `desvio_bruto_m`.
- Atributos extras de `linhas_corrigidas` mantidos; limiar de revisão manual 0,30 (hipótese).
- Linha que cruza mais de um talhão ou só parcialmente contida: `ErroContrato`.
- Estação sem valor e sem estação boa nas duas pontas: linha projetada mantida, `duvidoso`.
- `limite_variacao_m` absoluto entre estações vizinhas.
- Ponto da estação: linha projetada deslocada por `desvio_m`.
- Pixels em nodata: sem dado.
- CRS comparado por equivalência (`CRS.equals`).
