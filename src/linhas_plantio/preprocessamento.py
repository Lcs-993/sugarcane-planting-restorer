"""Módulo preprocessamento: recorte por talhão e índice de vegetação, com leitura por janelas
(docs/interfaces-fase1.md, seção 6.2)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.errors import WindowError
from rasterio.windows import Window, from_bounds

from .config import Config
from .tipos import AreaTalhao, ErroContrato, JanelaRaster, Talhao

# VARI explode quando o denominador tende a zero. O recorte em [-1, 1] é uma escolha de
# implementação, HIPÓTESE sem fonte lida, para manter o histograma do Otsu utilizável.
VARI_LIMITE = 1.0


def calcular_indice(bandas: np.ndarray, cfg: Config) -> np.ndarray:
    """Função pura. `bandas`: (n, h, w) na ordem [R, G, B] e, para ndvi, [R, G, B, NIR].

    Devolve (h, w) float32 com o índice de cfg.indice (exg, vari ou ndvi).
    exg usa coordenadas cromáticas (r = R/(R+G+B), ...): ExG = 2g - r - b.
    Divisão por zero (e valores não finitos) vira NaN.
    """
    b = np.asarray(bandas, dtype=np.float64)
    if b.ndim != 3:
        raise ErroContrato("bandas deve ter formato (n, altura, largura)")
    r, g, bl = b[0], b[1], b[2]
    with np.errstate(divide="ignore", invalid="ignore"):
        if cfg.indice == "exg":
            soma = r + g + bl
            idx = (2 * g - r - bl) / soma
        elif cfg.indice == "vari":
            idx = (g - r) / (g + r - bl)
            idx = np.where(np.isfinite(idx), np.clip(idx, -VARI_LIMITE, VARI_LIMITE), np.nan)
        elif cfg.indice == "ndvi":
            if b.shape[0] < 4:
                raise ErroContrato("ndvi exige a banda do infravermelho próximo como quarta banda")
            nir = b[3]
            idx = (nir - r) / (nir + r)
        else:  # pragma: no cover - Config já valida
            raise ErroContrato(f"índice desconhecido: {cfg.indice}")
    idx = np.where(np.isfinite(idx), idx, np.nan)
    return idx.astype(np.float32)


class FonteIndice:
    """Leitor preguiçoso do índice de vegetação; lê o GeoTIFF por janelas."""

    def __init__(self, caminho: Path, cfg: Config):
        self._cfg = cfg
        self._ds = rasterio.open(caminho)
        n = self._ds.count
        self._bandas = list(cfg.bandas_rgb) + ([cfg.banda_nir] if cfg.indice == "ndvi" else [])
        if cfg.indice == "ndvi" and cfg.banda_nir is None:
            self._ds.close()
            raise ErroContrato("indice ndvi exige banda_nir na configuração")
        ausentes = [b for b in self._bandas if b < 1 or b > n]
        if ausentes:
            self._ds.close()
            raise ErroContrato(f"banda(s) {ausentes} inexistente(s): o raster tem {n} banda(s)")
        self.crs: CRS = CRS.from_user_input(self._ds.crs)
        self.resolucao_m: float = abs(self._ds.transform.a)

    def ler_janela(self, bounds: tuple[float, float, float, float]) -> JanelaRaster:
        """Lê a janela cobrindo `bounds` (arredondada para fora, na grade do raster) e devolve o
        índice (float32). `validade` é False em nodata.

        Raises:
            ErroContrato: bounds não intersecta o raster.
        """
        esq, baixo, dir_, topo = bounds
        w = from_bounds(esq, baixo, dir_, topo, transform=self._ds.transform)
        col0, lin0 = math.floor(w.col_off + 1e-9), math.floor(w.row_off + 1e-9)
        col1, lin1 = math.ceil(w.col_off + w.width - 1e-9), math.ceil(w.row_off + w.height - 1e-9)
        janela = Window(col0, lin0, max(col1 - col0, 1), max(lin1 - lin0, 1))
        try:
            janela = janela.intersection(Window(0, 0, self._ds.width, self._ds.height))
        except WindowError as exc:
            raise ErroContrato("a janela pedida não intersecta o ortomosaico") from exc
        if janela.width < 1 or janela.height < 1:
            raise ErroContrato("a janela pedida não intersecta o ortomosaico")
        bandas = self._ds.read(self._bandas, window=janela).astype(np.float32)
        mascara = self._ds.dataset_mask(window=janela) > 0
        indice = calcular_indice(bandas, self._cfg)
        validade = mascara & np.isfinite(indice)
        valores = np.where(validade, indice, np.float32(np.nan)).astype(np.float32)
        return JanelaRaster(valores=valores, validade=validade, transform=self._ds.window_transform(janela))

    def fechar(self) -> None:
        self._ds.close()

    def __enter__(self) -> "FonteIndice":
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()


def abrir_fonte_indice(caminho_ortomosaico: Path, cfg: Config) -> FonteIndice:
    """Abre o raster e prepara o cálculo do índice de cfg.indice sob demanda por janela.

    Raises:
        ErroContrato: banda indicada inexistente; ndvi sem banda_nir.
    """
    return FonteIndice(Path(caminho_ortomosaico), cfg)


def recortar_talhao(talhao: Talhao, cfg: Config) -> AreaTalhao:
    """Aplica buffer interno negativo (cfg.buffer_interno_m) e calcula bounds.

    Raises:
        ErroContrato: o polígono útil fica vazio.
    """
    util = talhao.poligono.buffer(-cfg.buffer_interno_m)
    if util.is_empty:
        raise ErroContrato(
            f"talhão {talhao.id!r}: o buffer interno de {cfg.buffer_interno_m} m esvazia o polígono útil"
        )
    return AreaTalhao(talhao=talhao, poligono_util=util, bounds=tuple(util.bounds))
