"""Gerador de dados sintéticos para os testes.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.

Cenário: talhão retangular de 100 m x 36 m, ortomosaico RGB a 3 cm por pixel, 7 passadas de
3 m, cada uma com um par de fileiras (centros a 1,50 m, faixas de 0,48 m). As linhas de piloto
vão de oeste para leste, então a esquerda do sentido de digitalização é o norte (+y).
As fileiras reais são deslocadas da linha projetada por um perfil de deriva conhecido.
Coordenadas locais (x, y) em metros a partir da origem do talhão; CRS projetado em metros.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

CRS_SINTETICO = "EPSG:31983"  # SIRGAS 2000 / UTM 23S, metros
ORIGEM_X = 700000.0
ORIGEM_Y = 7800000.0
PIXEL_M = 0.03
COMPRIMENTO_M = 100.0
LARGURA_M = 36.0
EIXOS_Y = [10.0 + 3.0 * k for k in range(7)]  # linhas de piloto projetadas, P0..P6
X_INI, X_FIM = 10.0, 90.0
LARGURA_FAIXA_M = 0.48  # dentro de 45 a 50 cm
ESPACAMENTO_GEMEAS_M = 1.50

# (índice da passada, lado, x inicial, x final) em coordenadas locais; lado: esq | dir | ambas
LACUNAS_PADRAO: list[tuple[int, str, float, float]] = [
    (1, "dir", 33.0, 34.2),  # falha de planta entre estações (estações em x = 10, 20, ..., 90)
    (3, "esq", 63.5, 64.5),  # falha de planta entre estações
    (5, "ambas", 22.0, 23.0),  # falha nas duas fileiras entre estações
    (2, "esq", 28.5, 31.5),  # cobre a estação x = 30: só a fileira direita fica
    (4, "ambas", 45.0, 65.0),  # trecho sem fileira detectável (estações x = 50 e 60)
]


def deriva_constante(valor_m: float = 0.30) -> Callable[[np.ndarray], np.ndarray]:
    return lambda x: np.full_like(np.asarray(x, dtype=float), valor_m)


def deriva_rotacao(inicio_m: float = -0.30, fim_m: float = 0.30) -> Callable[[np.ndarray], np.ndarray]:
    def f(x):
        x = np.asarray(x, dtype=float)
        return inicio_m + (fim_m - inicio_m) * (x - X_INI) / (X_FIM - X_INI)

    return f


def deriva_senoidal(amplitude_m: float = 0.20, periodo_m: float = 60.0) -> Callable[[np.ndarray], np.ndarray]:
    return lambda x: amplitude_m * np.sin(2 * np.pi * (np.asarray(x, dtype=float) - X_INI) / periodo_m)


@dataclass
class Caso:
    raster: Path
    talhoes: Path
    linhas: Path
    deriva: Callable[[np.ndarray], np.ndarray]
    ids_passadas: list[str] = field(default_factory=list)
    crs: str = CRS_SINTETICO


def _renderizar(deriva, lacunas, ajustes_dir_m) -> np.ndarray:
    n_cols = int(round(COMPRIMENTO_M / PIXEL_M))
    n_rows = int(round(LARGURA_M / PIXEL_M))
    rng = np.random.default_rng(42)
    solo = np.array([150.0, 115.0, 85.0])
    cana = np.array([55.0, 130.0, 45.0])
    img = solo[:, None, None] + rng.normal(0, 5.0, size=(3, n_rows, n_cols))
    x_c = (np.arange(n_cols) + 0.5) * PIXEL_M
    for k, eixo in enumerate(EIXOS_Y):
        for lado, sinal in (("esq", +1.0), ("dir", -1.0)):
            yc = eixo + sinal * ESPACAMENTO_GEMEAS_M / 2 + deriva(x_c)
            if lado == "dir":
                yc = yc + ajustes_dir_m.get(k, 0.0)
            y_min, y_max = yc.min() - LARGURA_FAIXA_M, yc.max() + LARGURA_FAIXA_M
            r0 = max(int(np.floor((LARGURA_M - y_max) / PIXEL_M)), 0)
            r1 = min(int(np.ceil((LARGURA_M - y_min) / PIXEL_M)), n_rows)
            y_c = LARGURA_M - (np.arange(r0, r1) + 0.5) * PIXEL_M
            mascara = np.abs(y_c[:, None] - yc[None, :]) <= LARGURA_FAIXA_M / 2
            for (kk, ld, xa, xb) in lacunas:
                if kk == k and ld in (lado, "ambas"):
                    mascara[:, (x_c >= xa) & (x_c <= xb)] = False
            ruido = rng.normal(0, 5.0, size=(3,) + mascara.shape)
            faixa = cana[:, None, None] + ruido
            sub = img[:, r0:r1, :]
            for b in range(3):
                sub[b][mascara] = faixa[b][mascara]
    return np.clip(img, 0, 255).astype(np.uint8)


def gerar_caso(
    pasta: Path,
    deriva: Callable[[np.ndarray], np.ndarray],
    lacunas: list[tuple[int, str, float, float]] | None = None,
    ajustes_dir_m: dict[int, float] | None = None,
    crs_talhoes: str | None = None,
) -> Caso:
    """Gera raster, talhão e linhas de piloto em `pasta`.

    ajustes_dir_m: deslocamento extra (m, +esquerda) da fileira direita de uma passada, para
    produzir espaçamento entre gêmeas fora da tolerância.
    crs_talhoes: grava o talhão em outro CRS, para testar o erro de CRS divergente.
    """
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    lacunas = LACUNAS_PADRAO if lacunas is None else lacunas
    img = _renderizar(deriva, lacunas, ajustes_dir_m or {})
    caminho_raster = pasta / "ortomosaico.tif"
    transform = from_origin(ORIGEM_X, ORIGEM_Y + LARGURA_M, PIXEL_M, PIXEL_M)
    with rasterio.open(
        caminho_raster, "w", driver="GTiff", height=img.shape[1], width=img.shape[2], count=3,
        dtype="uint8", crs=CRS_SINTETICO, transform=transform, tiled=True, blockxsize=256, blockysize=256,
    ) as ds:
        ds.write(img)

    talhao = gpd.GeoDataFrame(
        {"id": ["T1"]},
        geometry=[box(ORIGEM_X, ORIGEM_Y, ORIGEM_X + COMPRIMENTO_M, ORIGEM_Y + LARGURA_M)],
        crs=CRS_SINTETICO,
    )
    if crs_talhoes:
        talhao = talhao.to_crs(crs_talhoes)
    caminho_talhoes = pasta / "talhoes.gpkg"
    talhao.to_file(caminho_talhoes, driver="GPKG")

    ids = [f"P{k}" for k in range(len(EIXOS_Y))]
    linhas = gpd.GeoDataFrame(
        {"id": ids},
        geometry=[LineString([(ORIGEM_X + X_INI, ORIGEM_Y + y), (ORIGEM_X + X_FIM, ORIGEM_Y + y)]) for y in EIXOS_Y],
        crs=CRS_SINTETICO,
    )
    caminho_linhas = pasta / "linhas.gpkg"
    linhas.to_file(caminho_linhas, driver="GPKG")
    return Caso(caminho_raster, caminho_talhoes, caminho_linhas, deriva, ids)


def erros_laterais(linha_corrigida: LineString, indice_passada: int, deriva, ajuste_dir_m: float = 0.0):
    """Erro lateral (m) da linha corrigida e da linha projetada contra a deriva conhecida.

    O eixo real do par é eixo + deriva(x) (+ metade do ajuste da fileira direita, se houver).
    Devolve (erro_corrigida, erro_projetada), absolutos, amostrados a cada 1 m entre X_INI e X_FIM.
    """
    xs_loc = np.arange(X_INI, X_FIM + 1e-9, 1.0)
    coords = np.asarray(linha_corrigida.coords)
    x_loc = coords[:, 0] - ORIGEM_X
    y_loc = coords[:, 1] - ORIGEM_Y
    y_corr = np.interp(xs_loc, x_loc, y_loc)
    y_proj = EIXOS_Y[indice_passada]
    y_real = y_proj + deriva(xs_loc) + ajuste_dir_m / 2.0
    return np.abs(y_corr - y_real), np.abs(y_proj - y_real)


def preparar(caso: Caso, cfg):
    """Entrada, fonte do índice e fonte binária do talhão T1 de um caso sintético."""
    from linhas_plantio.entrada import carregar_entrada
    from linhas_plantio.preprocessamento import abrir_fonte_indice, recortar_talhao
    from linhas_plantio.segmentacao import abrir_fonte_binaria, calcular_limiar_otsu

    dados = carregar_entrada(caso.raster, caso.talhoes, caso.linhas, cfg)
    fonte = abrir_fonte_indice(caso.raster, cfg)
    area = recortar_talhao(dados.talhoes[0], cfg)
    fb = abrir_fonte_binaria(fonte, area, calcular_limiar_otsu(fonte, area))
    return dados, fonte, fb
