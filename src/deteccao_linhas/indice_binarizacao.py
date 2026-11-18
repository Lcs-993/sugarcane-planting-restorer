"""Índice de vegetação e binarização por janelas (docs/interfaces-deteccao.md, seção 6.2).

O ortomosaico nunca é lido inteiro: tudo passa por janelas, reduzidas por média de área.
DESVIO das interfaces: a 1ª passagem do Otsu (faixa do índice) é feita numa resolução mais grossa,
com a faixa ampliada em 5 % de cada lado, e a 2ª (histograma) corta o índice a essa faixa. Evita
decodificar duas vezes o raster inteiro na resolução de trabalho.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from shapely.geometry import box

from .config import Config
from .tipos import AreaTalhao, ErroConfig, ErroContrato, ErroDeteccao, ErroLeitura, JanelaRaster, Talhao

LADO_TILE_M = 100.0  # lado das janelas de varredura do talhão (só gerência de memória)
RESOLUCAO_FAIXA_M = 0.30  # resolução da 1ª passagem (faixa do índice)


def calcular_indice(bandas: np.ndarray, cfg: Config) -> np.ndarray:
    """Função pura. bandas (3, h, w) -> (h, w) float32. Divisão por zero vira NaN."""
    b = bandas.astype(np.float32)
    r, g, bl = b[0], b[1], b[2]
    with np.errstate(divide="ignore", invalid="ignore"):
        if cfg.indice == "exg":
            if cfg.variante_exg == "normalizado":
                soma = r + g + bl
                out = (2.0 * g - r - bl) / soma
            else:
                out = 2.0 * g - r - bl
        else:  # vari
            out = (g - r) / (g + r - bl)
    out = out.astype(np.float32)
    out[~np.isfinite(out)] = np.nan
    return out


class FonteIndice:
    """Leitor preguiçoso do índice de vegetação; lê o GeoTIFF por janelas."""

    def __init__(self, caminho: Path, cfg: Config) -> None:
        self._cfg = cfg
        try:
            self._ds = rasterio.open(caminho)
        except rasterio.errors.RasterioIOError as exc:
            raise ErroLeitura(f"não foi possível abrir o ortomosaico {caminho}: {exc}") from exc
        t = self._ds.transform
        if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
            self._ds.close()
            raise ErroContrato("ortomosaico com transformação rotacionada ou invertida não é suportado")
        self.crs = self._ds.crs
        self.resolucao_nativa_m = float(min(abs(t.a), abs(t.e)))
        self.bounds_raster = tuple(self._ds.bounds)
        self._bandas = list(cfg.bandas_rgb)

    def ler_janela(self, bounds: tuple[float, float, float, float],
                   resolucao_m: float | None = None) -> JanelaRaster:
        """Índice float32 na janela, reduzido por média de área para `resolucao_m`.

        Raises: ErroContrato se bounds não intersecta o raster; ErroConfig se resolucao_m < nativa.
        """
        res = self._cfg.resolucao_trabalho_m if resolucao_m is None else float(resolucao_m)
        if res < self.resolucao_nativa_m * (1 - 1e-6):
            raise ErroConfig(f"resolucao_m={res} menor que a resolução nativa {self.resolucao_nativa_m:.4f} m")
        rx0, ry0, rx1, ry1 = self.bounds_raster
        x0, y0 = max(bounds[0], rx0), max(bounds[1], ry0)
        x1, y1 = min(bounds[2], rx1), min(bounds[3], ry1)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            raise ErroContrato("bounds não intersecta o ortomosaico")
        w = max(1, int(round((x1 - x0) / res)))
        h = max(1, int(round((y1 - y0) / res)))
        janela = from_bounds(x0, y0, x1, y1, transform=self._ds.transform)
        n = len(self._bandas)
        dados = self._ds.read(self._bandas, window=janela, out_shape=(n, h, w),
                              resampling=Resampling.average, boundless=False).astype(np.float32)
        mascaras = self._ds.read_masks(self._bandas, window=janela, out_shape=(n, h, w),
                                       resampling=Resampling.average, boundless=False)
        validade = (mascaras >= 128).all(axis=0)
        indice = calcular_indice(dados, self._cfg)
        validade &= np.isfinite(indice)
        transform = from_origin(x0, y1, (x1 - x0) / w, (y1 - y0) / h)
        return JanelaRaster(valores=indice, validade=validade, transform=transform)

    def fechar(self) -> None:
        self._ds.close()


def abrir_fonte_indice(caminho_ortomosaico: Path, cfg: Config) -> FonteIndice:
    return FonteIndice(Path(caminho_ortomosaico), cfg)


def recortar_talhao(talhao: Talhao, cfg: Config) -> AreaTalhao:
    """Buffer interno negativo (cfg.buffer_interno_m) e bounds.

    Raises: ErroContrato se a área útil ficar vazia.
    """
    util = talhao.poligono.buffer(-cfg.buffer_interno_m)
    if util.is_empty:
        raise ErroContrato(f"talhão {talhao.id!r}: área útil vazia após buffer interno de {cfg.buffer_interno_m} m")
    return AreaTalhao(talhao=talhao, poligono_util=util, bounds=tuple(util.bounds))


def _mascara_area(area: AreaTalhao, janela: JanelaRaster) -> np.ndarray:
    h, w = janela.valores.shape
    x0, y1 = janela.transform * (0, 0)
    x1, y0 = janela.transform * (w, h)
    recorte = area.poligono_util.intersection(box(x0, y0, x1, y1))
    if recorte.is_empty:
        return np.zeros((h, w), dtype=bool)
    return ~geometry_mask([recorte], out_shape=(h, w), transform=janela.transform, all_touched=False)


def _tiles(bounds: tuple[float, float, float, float], lado: float):
    x = bounds[0]
    while x < bounds[2]:
        y = bounds[1]
        while y < bounds[3]:
            yield (x, y, min(x + lado, bounds[2]), min(y + lado, bounds[3]))
            y += lado
        x += lado


def _otsu_histograma(contagens: np.ndarray, centros: np.ndarray) -> float:
    total = contagens.sum()
    p = contagens / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * centros)
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega))
    sigma_b[~np.isfinite(sigma_b)] = -1.0
    k = int(np.argmax(sigma_b))
    # limiar na borda superior do bin k: "índice >= limiar é vegetação"
    passo = centros[1] - centros[0]
    return float(centros[k] + passo / 2.0)


def calcular_limiar_otsu(fonte: FonteIndice, area: AreaTalhao, cfg: Config) -> float:
    """Otsu por talhão, com histograma acumulado por janelas.

    Raises: ErroDeteccao se a área útil não tiver pixels válidos.
    """
    res_faixa = max(RESOLUCAO_FAIXA_M, cfg.resolucao_trabalho_m)
    vmin, vmax = np.inf, -np.inf
    for tb in _tiles(area.bounds, LADO_TILE_M):
        try:
            jan = fonte.ler_janela(tb, res_faixa)
        except ErroContrato:
            continue
        ok = jan.validade & _mascara_area(area, jan)
        if ok.any():
            v = jan.valores[ok]
            vmin, vmax = min(vmin, float(v.min())), max(vmax, float(v.max()))
    if not np.isfinite(vmin) or vmax <= vmin:
        raise ErroDeteccao(f"talhão {area.talhao.id!r}: área útil sem pixels válidos (ou índice constante)")
    folga = 0.05 * (vmax - vmin)
    lo, hi = vmin - folga, vmax + folga
    bordas = np.linspace(lo, hi, cfg.n_bins_otsu + 1)
    centros = (bordas[:-1] + bordas[1:]) / 2.0
    contagens = np.zeros(cfg.n_bins_otsu, dtype=np.int64)
    for tb in _tiles(area.bounds, LADO_TILE_M):
        try:
            jan = fonte.ler_janela(tb, cfg.resolucao_trabalho_m)
        except ErroContrato:
            continue
        ok = jan.validade & _mascara_area(area, jan)
        if ok.any():
            v = np.clip(jan.valores[ok], lo, hi)
            contagens += np.histogram(v, bins=bordas)[0]
    if contagens.sum() == 0:
        raise ErroDeteccao(f"talhão {area.talhao.id!r}: área útil sem pixels válidos")
    return _otsu_histograma(contagens, centros)


class FonteBinaria:
    """Leitor preguiçoso do raster binário (True = vegetação) de um talhão."""

    def __init__(self, fonte: FonteIndice, area: AreaTalhao, limiar: float, cfg: Config) -> None:
        self._fonte, self._area, self.limiar, self._cfg = fonte, area, limiar, cfg

    @property
    def area(self) -> AreaTalhao:
        return self._area

    def ler_janela(self, bounds: tuple[float, float, float, float],
                   resolucao_m: float | None = None) -> JanelaRaster:
        """valores bool; validade False fora da área útil e em nodata."""
        jan = self._fonte.ler_janela(bounds, resolucao_m)
        validade = jan.validade & _mascara_area(self._area, jan)
        valores = np.zeros(jan.valores.shape, dtype=bool)
        valores[validade] = jan.valores[validade] >= self.limiar
        return JanelaRaster(valores=valores, validade=validade, transform=jan.transform)


def abrir_fonte_binaria(fonte: FonteIndice, area: AreaTalhao, limiar: float, cfg: Config) -> FonteBinaria:
    """Binariza por janela: índice >= limiar é vegetação."""
    return FonteBinaria(fonte, area, limiar, cfg)
