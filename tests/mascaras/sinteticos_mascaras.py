"""Ortomosaico sintético com fileiras de cana, manchas de daninha e solo.

AVISO: prova só que o fluxo funciona. As cores são inventadas e separáveis de propósito: nada aqui diz
se o classificador separa cana de daninha em imagem real (hipótese M2 de docs/escopo-mascaras.md).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

CRS_M = "EPSG:31983"
ORIGEM = (394000.0, 7775000.0)  # canto noroeste
CANA_RGB = (60, 160, 50)
DANINHA_RGB = (150, 200, 30)  # verde-amarelado (inventado)
SOLO_RGB = (150, 110, 80)
SOMBRA_RGB = (25, 25, 30)
ESPACAMENTO = 1.5
FASE = 0.3
LARGURA_FAIXA = 0.48


def centros_fileiras(largura_m: float) -> list[float]:
    """Posição x (relativa à origem) do centro de cada fileira."""
    return [FASE + ESPACAMENTO * k for k in range(int((largura_m - FASE) / ESPACAMENTO) + 1)]


def manchas_daninha(largura_m: float, altura_m: float, n: int = 12, raio_m: float = 0.25, semente: int = 1):
    """Centros (x, y relativos; y para o sul) entre fileiras, longe das faixas."""
    rng = np.random.default_rng(semente)
    saida = []
    for _ in range(n):
        k = rng.integers(0, int(largura_m / ESPACAMENTO) - 1)
        x = FASE + ESPACAMENTO * k + ESPACAMENTO / 2
        y = float(rng.uniform(3, altura_m - 3))
        saida.append((x, y, raio_m))
    return saida


def gerar_orto(caminho: Path, *, largura_m: float = 30.0, altura_m: float = 30.0, res_m: float = 0.03,
               daninhas=None, sombra: tuple[float, float, float, float] | None = None, ruido: float = 3.0,
               semente: int = 0, crs: str = CRS_M) -> Path:
    """Fileiras norte-sul. `daninhas`: [(x, y_sul, raio)]. `sombra`: (x0, y0, x1, y1) relativos, y para o sul."""
    rng = np.random.default_rng(semente)
    h, w = int(round(altura_m / res_m)), int(round(largura_m / res_m))
    X, Y = np.meshgrid((np.arange(w) + 0.5) * res_m, (np.arange(h) + 0.5) * res_m)
    d = np.abs(((X - FASE + ESPACAMENTO / 2) % ESPACAMENTO) - ESPACAMENTO / 2)
    cana = d <= LARGURA_FAIXA / 2
    dan = np.zeros_like(cana)
    for x, y, r in daninhas or []:
        dan |= (X - x) ** 2 + (Y - y) ** 2 <= r * r
    dan &= ~cana
    img = np.zeros((3, h, w), dtype=np.float32)
    for b in range(3):
        img[b] = np.where(cana, CANA_RGB[b], np.where(dan, DANINHA_RGB[b], SOLO_RGB[b]))
    if sombra is not None:
        x0, y0, x1, y1 = sombra
        s = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1) & ~cana & ~dan
        for b in range(3):
            img[b][s] = SOMBRA_RGB[b]
    img = np.clip(img + rng.normal(0, ruido, img.shape), 0, 255).astype(np.uint8)
    with rasterio.open(caminho, "w", driver="GTiff", height=h, width=w, count=3, dtype="uint8", crs=crs,
                       transform=from_origin(ORIGEM[0], ORIGEM[1], res_m, res_m)) as ds:
        ds.write(img)
    return caminho


def gerar_talhao(caminho: Path, largura_m: float = 30.0, altura_m: float = 30.0, ident: str = "T1",
                 crs: str = CRS_M) -> Path:
    gdf = gpd.GeoDataFrame({"id": [ident]}, geometry=[box(ORIGEM[0], ORIGEM[1] - altura_m,
                                                          ORIGEM[0] + largura_m, ORIGEM[1])], crs=crs)
    gdf.to_file(caminho, driver="GPKG")
    return caminho


def gerar_deteccao(caminho: Path, largura_m: float = 30.0, altura_m: float = 30.0, passo_m: float = 5.0,
                   status=None, crs: str = CRS_M) -> Path:
    """GeoPackage no formato da detecção (camadas fileiras e trechos) com as fileiras na posição certa.
    `status`: função (indice_fileira, indice_ponto) -> (status, confiança); padrão detectado, 0,9."""
    status = status or (lambda i, j: ("detectado", 0.9))
    linhas, pts = [], []
    ys = np.arange(ORIGEM[1] - 0.5, ORIGEM[1] - altura_m + 0.5, -passo_m)
    for i, xr in enumerate(centros_fileiras(largura_m)):
        x = ORIGEM[0] + xr
        idf = f"T1-F{i + 1:04d}"
        linhas.append((idf, LineString([(x, y) for y in ys])))
        for j, y in enumerate(ys):
            s, c = status(i, j)
            pts.append((idf, float(j * passo_m), s, c, Point(x, y)))
    gpd.GeoDataFrame({"id_fileira": [a for a, _ in linhas], "talhao": "T1"}, geometry=[g for _, g in linhas],
                     crs=crs).to_file(caminho, layer="fileiras", driver="GPKG")
    gpd.GeoDataFrame({"id_fileira": [p[0] for p in pts], "posicao_m": [p[1] for p in pts],
                      "status": [p[2] for p in pts], "confianca": [p[3] for p in pts]},
                     geometry=[p[4] for p in pts], crs=crs).to_file(caminho, layer="trechos", driver="GPKG",
                                                                   mode="a")
    return caminho
