"""Gerador sintético de ortomosaico de fileiras (só prova que o algoritmo funciona, não acurácia)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

CRS_M = "EPSG:31983"


def gerar_fileiras(
    caminho: Path,
    *,
    largura_m: float = 60.0,
    altura_m: float = 60.0,
    res_m: float = 0.06,
    origem: tuple[float, float] = (394000.0, 7775000.0),  # canto noroeste
    angulo_graus: float = 0.0,  # azimute das fileiras (0 = norte-sul)
    espacamento_m: float = 1.5,
    largura_faixa_m: float = 0.48,
    fase_m: float = 0.3,
    falha: tuple[float, float, float, float] | None = None,  # (s0,s1,t0,t1) em metros locais, zera vegetação
    ruido: float = 0.0,
    semente: int = 0,
    crs: str = CRS_M,
) -> Path:
    """Fileiras de vegetação (verde) sobre solo (marrom). Posição lateral t = x*cos(a) - y*sin(a) no
    sistema leste/norte relativo à origem; fileiras alinhadas ao azimute `angulo_graus`."""
    rng = np.random.default_rng(semente)
    h, w = int(round(altura_m / res_m)), int(round(largura_m / res_m))
    cols = (np.arange(w) + 0.5) * res_m
    lins = (np.arange(h) + 0.5) * res_m
    X, Yd = np.meshgrid(cols, lins)  # Yd cresce para o sul
    Y = altura_m - Yd  # norte relativo
    a = np.deg2rad(angulo_graus)
    u = (np.sin(a), np.cos(a))  # (leste, norte)
    s = X * u[0] + Y * u[1]
    t = X * u[1] - Y * u[0]  # normal à direita... apenas coordenada lateral consistente
    d = np.abs(((t - fase_m + espacamento_m / 2) % espacamento_m) - espacamento_m / 2)
    veg = d <= largura_faixa_m / 2
    if falha is not None:
        s0, s1, t0, t1 = falha
        veg &= ~((s >= s0) & (s <= s1) & (t >= t0) & (t <= t1))
    img = np.zeros((3, h, w), dtype=np.uint8)
    solo = np.array([150, 110, 80])
    verde = np.array([60, 160, 50])
    for b in range(3):
        img[b] = np.where(veg, verde[b], solo[b])
    if ruido > 0:
        img = np.clip(img + rng.normal(0, ruido, img.shape), 0, 255).astype(np.uint8)
    tr = from_origin(origem[0], origem[1], res_m, res_m)
    with rasterio.open(caminho, "w", driver="GTiff", height=h, width=w, count=3, dtype="uint8",
                       crs=crs, transform=tr) as ds:
        ds.write(img)
    return caminho


def gerar_talhao(caminho: Path, bounds: tuple[float, float, float, float], ident="T1", crs: str = CRS_M) -> Path:
    gdf = gpd.GeoDataFrame({"id": [ident]}, geometry=[box(*bounds)], crs=crs)
    gdf.to_file(caminho, driver="GPKG")
    return caminho


@pytest.fixture
def ortho_simples(tmp_path):
    """60x60 m, fileiras norte-sul a 1,5 m, talhão cobrindo tudo."""
    tif = gerar_fileiras(tmp_path / "orto.tif")
    gpkg = gerar_talhao(tmp_path / "talhao.gpkg", (394000.0, 7774940.0, 394060.0, 7775000.0))
    return tif, gpkg
