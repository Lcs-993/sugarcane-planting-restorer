"""Fonte do perfil a partir da máscara de classes (docs/escopo-mascaras.md, seção 5).

Mesma interface de FonteBinaria (`area`, `ler_janela(bounds, resolucao_m) -> JanelaRaster`), para que
nenhuma outra etapa da detecção mude. Lê o GeoTIFF gravado por `python -m mascaras classificar` como
arquivo: não importa o pacote `mascaras`. Os códigos abaixo são os da seção 3 do escopo.

valores = True onde a classe é cana. HIPÓTESE (seção 5): sombra e ignorado (inclui sem dado) ficam
com validade False, fora do perfil; daninha e fundo ficam válidos e False.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

from .entrada import verificar_crs
from .indice_binarizacao import _mascara_area
from .tipos import AreaTalhao, ErroConfig, ErroContrato, ErroLeitura, JanelaRaster

IGNORADO, CANA, DANINHA, FUNDO, SOMBRA = 0, 1, 2, 3, 4
CLASSES_INVALIDAS = (IGNORADO, SOMBRA)
TOLERANCIA_RES = 1e-3  # fração; a máscara precisa estar na resolução de trabalho da detecção


class RasterMascara:
    """GeoTIFF de classes aberto uma vez e lido por janelas (compartilhado entre talhões)."""

    def __init__(self, caminho: Path, crs_ortomosaico, resolucao_trabalho_m: float) -> None:
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ErroLeitura(f"máscara de classes não encontrada: {caminho}")
        try:
            self._ds = rasterio.open(caminho)
        except rasterio.errors.RasterioIOError as exc:
            raise ErroLeitura(f"não foi possível abrir a máscara {caminho}: {exc}") from exc
        try:
            verificar_crs({"ortomosaico": CRS.from_user_input(crs_ortomosaico) if crs_ortomosaico else None,
                           "mascara": CRS.from_user_input(self._ds.crs) if self._ds.crs else None})
            if self._ds.count != 1 or self._ds.dtypes[0] != "uint8":
                raise ErroContrato(f"{caminho.name}: a máscara deve ter uma banda uint8 (códigos 0 a 4)")
            t = self._ds.transform
            if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
                raise ErroContrato("máscara com transformação rotacionada ou invertida não é suportada")
            self.res = float(abs(t.a))
            if abs(self.res - resolucao_trabalho_m) > TOLERANCIA_RES * resolucao_trabalho_m:
                raise ErroConfig(
                    f"a máscara tem pixel de {self.res:.4f} m e a detecção usa resolucao_trabalho_m="
                    f"{resolucao_trabalho_m} m. Gere a máscara na mesma resolução (configuração do pacote mascaras).")
        except Exception:
            self._ds.close()
            raise
        b = self._ds.bounds
        self.bounds = (b.left, b.bottom, b.right, b.top)

    def ler_classes(self, bounds: tuple[float, float, float, float], resolucao_m: float):
        """Códigos de classe na janela (vizinho mais próximo) e o transform; None se fora da máscara."""
        if abs(resolucao_m - self.res) > TOLERANCIA_RES * self.res:
            raise ErroConfig(f"leitura da máscara em {resolucao_m} m; a máscara tem {self.res:.4f} m")
        rx0, ry0, rx1, ry1 = self.bounds
        x0, y0 = max(bounds[0], rx0), max(bounds[1], ry0)
        x1, y1 = min(bounds[2], rx1), min(bounds[3], ry1)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            raise ErroContrato("bounds não intersecta a máscara de classes")
        w = max(1, int(round((x1 - x0) / resolucao_m)))
        h = max(1, int(round((y1 - y0) / resolucao_m)))
        janela = from_bounds(x0, y0, x1, y1, transform=self._ds.transform)
        cls = self._ds.read(1, window=janela, out_shape=(h, w), resampling=Resampling.nearest)
        return cls, from_origin(x0, y1, (x1 - x0) / w, (y1 - y0) / h)

    def fechar(self) -> None:
        self._ds.close()


class FonteMascara:
    """Leitor preguiçoso da máscara de classes de um talhão (True = cana)."""

    def __init__(self, raster: RasterMascara, area: AreaTalhao, resolucao_trabalho_m: float) -> None:
        self._raster, self._area, self._res = raster, area, resolucao_trabalho_m

    @property
    def area(self) -> AreaTalhao:
        return self._area

    def ler_janela(self, bounds: tuple[float, float, float, float],
                   resolucao_m: float | None = None) -> JanelaRaster:
        res = self._res if resolucao_m is None else float(resolucao_m)
        cls, transform = self._raster.ler_classes(bounds, res)
        provisoria = JanelaRaster(valores=cls, validade=np.ones(cls.shape, dtype=bool), transform=transform)
        validade = ~np.isin(cls, CLASSES_INVALIDAS) & _mascara_area(self._area, provisoria)
        valores = validade & (cls == CANA)
        return JanelaRaster(valores=valores, validade=validade, transform=transform)


def abrir_raster_mascara(caminho: Path, crs_ortomosaico, resolucao_trabalho_m: float) -> RasterMascara:
    return RasterMascara(caminho, crs_ortomosaico, resolucao_trabalho_m)


def abrir_fonte_mascara(raster: RasterMascara, area: AreaTalhao, resolucao_trabalho_m: float) -> FonteMascara:
    return FonteMascara(raster, area, resolucao_trabalho_m)
