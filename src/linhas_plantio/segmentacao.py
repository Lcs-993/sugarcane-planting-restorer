"""Módulo segmentacao: binarização por talhão com Otsu calculado em cada talhão
(docs/interfaces-fase1.md, seção 6.3). O raster do talhão nunca fica inteiro na memória."""
from __future__ import annotations

from typing import Iterator

import numpy as np
from pyproj import CRS
from rasterio.features import geometry_mask
from skimage.filters import threshold_otsu

from .preprocessamento import FonteIndice
from .tipos import AreaTalhao, ErroContrato, JanelaRaster

# Lado do bloco de leitura, em pixels. Escolha técnica de memória, não afeta o resultado.
LADO_BLOCO_PX = 2048


def _mascara_poligono(poligono, forma: tuple[int, int], transform) -> np.ndarray:
    """True onde o centro do pixel cai dentro do polígono."""
    return geometry_mask([poligono], out_shape=forma, transform=transform, invert=True, all_touched=False)


def _iterar_blocos(fonte: FonteIndice, area: AreaTalhao) -> Iterator[np.ndarray]:
    """Valores válidos do índice dentro da área útil, bloco a bloco, sem repetir pixels."""
    esq, baixo, dir_, topo = area.bounds
    lado = LADO_BLOCO_PX * fonte.resolucao_m
    x0 = esq
    while x0 < dir_:
        x1 = min(x0 + lado, dir_)
        y0 = baixo
        while y0 < topo:
            y1 = min(y0 + lado, topo)
            try:
                jan = fonte.ler_janela((x0, y0, x1, y1))
            except ErroContrato:
                y0 = y1
                continue
            h, w = jan.valores.shape
            t = jan.transform
            xs = t.c + (np.arange(w) + 0.5) * t.a
            ys = t.f + (np.arange(h) + 0.5) * t.e
            dentro_bloco = ((xs >= x0) & (xs < x1))[None, :] & ((ys >= y0) & (ys < y1))[:, None]
            mascara = jan.validade & dentro_bloco & _mascara_poligono(area.poligono_util, (h, w), t)
            if mascara.any():
                yield jan.valores[mascara]
            y0 = y1
        x0 = x1


def calcular_limiar_otsu(fonte: FonteIndice, area: AreaTalhao, n_bins: int = 256) -> float:
    """Otsu calculado em cada talhão.

    O histograma é acumulado lendo a área útil por janelas (duas passagens: faixa de valores e
    histograma).

    Raises:
        ErroContrato: a área útil não tem pixels válidos ou o índice não varia.
    """
    vmin, vmax, n = np.inf, -np.inf, 0
    for v in _iterar_blocos(fonte, area):
        vmin, vmax, n = min(vmin, float(v.min())), max(vmax, float(v.max())), n + v.size
    if n == 0:
        raise ErroContrato(f"talhão {area.talhao.id!r}: a área útil não tem pixels válidos")
    if not vmax > vmin:
        raise ErroContrato(f"talhão {area.talhao.id!r}: o índice de vegetação não varia; Otsu indefinido")
    contagem = np.zeros(n_bins, dtype=np.int64)
    for v in _iterar_blocos(fonte, area):
        c, bordas = np.histogram(v, bins=n_bins, range=(vmin, vmax))
        contagem += c
    bordas = np.linspace(vmin, vmax, n_bins + 1)
    centros = (bordas[:-1] + bordas[1:]) / 2.0
    return float(threshold_otsu(hist=(contagem, centros)))


class FonteBinaria:
    """Leitor preguiçoso do raster binário (True = cana) de um talhão."""

    def __init__(self, fonte: FonteIndice, area: AreaTalhao, limiar: float):
        self._fonte = fonte
        self._area = area
        self.limiar = limiar
        self.resolucao_m: float = fonte.resolucao_m
        self.crs: CRS = fonte.crs

    def ler_janela(self, bounds: tuple[float, float, float, float]) -> JanelaRaster:
        """`valores` bool; `validade` False fora do polígono útil e em nodata.

        Raises:
            ErroContrato: bounds não intersecta o raster.
        """
        jan = self._fonte.ler_janela(bounds)
        validade = jan.validade & _mascara_poligono(self._area.poligono_util, jan.valores.shape, jan.transform)
        with np.errstate(invalid="ignore"):
            valores = (jan.valores >= self.limiar) & validade
        return JanelaRaster(valores=valores, validade=validade, transform=jan.transform)


def abrir_fonte_binaria(fonte: FonteIndice, area: AreaTalhao, limiar: float) -> FonteBinaria:
    """Binariza por janela: índice >= limiar é cana."""
    return FonteBinaria(fonte, area, limiar)
