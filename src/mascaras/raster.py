"""Grade de trabalho, leitura do ortomosaico por janelas, talhões e gravação de GeoTIFF.

O ortomosaico nunca é lido inteiro. A grade de saída tem origem no canto noroeste do ortomosaico e
pixel de `resolucao_trabalho_m`: fica alinhada à dele (escopo, seção 4). Nada é reprojetado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import geopandas as gpd
import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from .tipos import ErroConfig, ErroContrato, ErroCRS, ErroLeitura

EXTENSOES_VETORIAIS = {".gpkg", ".shp"}
BLOCO_TIFF = 256  # lado dos blocos dos GeoTIFF gravados


# ---------------------------------------------------------------- CRS

def _rotulo_crs(crs: CRS) -> str:
    auth = crs.to_authority()
    return f"{auth[0]}:{auth[1]}" if auth else crs.name


def _sem_towgs84_nulo(crs: CRS) -> CRS:
    """Ignora só um TOWGS84 com todos os parâmetros nulos (mesma regra da detecção)."""
    if not crs.is_bound:
        return crs
    params = crs.to_json_dict().get("transformation", {}).get("parameters", [])
    if params and all(float(p.get("value", 1.0)) == 0.0 for p in params):
        return crs.source_crs
    return crs


def verificar_crs(camadas: dict[str, object]) -> CRS:
    """Todas as camadas no mesmo CRS projetado em metros; devolve o do primeiro item. Não reprojeta.

    Raises: ErroCRS.
    """
    convertidos = {}
    for nome, c in camadas.items():
        if c is None:
            raise ErroCRS(f"CRS ausente em {nome}. Defina o CRS antes de rodar.")
        convertidos[nome] = _sem_towgs84_nulo(CRS.from_user_input(c))
    nomes = list(convertidos)
    ref = convertidos[nomes[0]]
    divergentes = [n for n in nomes[1:] if not convertidos[n].equals(ref)]
    if divergentes:
        lista = "; ".join(f"{n}={_rotulo_crs(c)}" for n, c in convertidos.items())
        raise ErroCRS(f"CRS divergente: {lista}. Reprojete as camadas antes de rodar.")
    unidade = ref.axis_info[0].unit_name.lower() if ref.axis_info else ""
    if not ref.is_projected or unidade not in ("metre", "meter"):
        raise ErroCRS(f"CRS ({_rotulo_crs(ref)}) não é projetado em metros.")
    return ref


# ---------------------------------------------------------------- vetores

def ler_vetor(caminho: Path, rotulo: str) -> gpd.GeoDataFrame:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroLeitura(f"arquivo de {rotulo} não encontrado: {caminho}")
    if caminho.suffix.lower() not in EXTENSOES_VETORIAIS:
        raise ErroLeitura(f"formato de {rotulo} não suportado ({caminho.suffix}); use .gpkg ou .shp")
    try:
        camada = None
        if caminho.suffix.lower() == ".gpkg":  # ignora a tabela de estilos que o QGIS grava no GeoPackage
            import pyogrio
            camadas = [str(n) for n, tipo in pyogrio.list_layers(caminho) if n != "layer_styles"]
            camada = camadas[0] if camadas else None
        return gpd.read_file(caminho, layer=camada)
    except Exception as exc:  # pyogrio levanta tipos variados
        raise ErroLeitura(f"não foi possível ler {rotulo} em {caminho}: {exc}") from exc


@dataclass(frozen=True)
class Talhoes:
    ids: tuple[str, ...]
    poligonos_util: tuple[Polygon | MultiPolygon, ...]  # com buffer interno
    uniao_util: Polygon | MultiPolygon


def ler_talhoes(caminho: Path, campo_id: str, buffer_interno_m: float, crs_ref) -> Talhoes:
    """Polígonos dos talhões com buffer interno. Raises: ErroLeitura, ErroCRS, ErroContrato."""
    gdf = ler_vetor(caminho, "talhões")
    if campo_id not in gdf.columns:
        campos = ", ".join(c for c in gdf.columns if c != "geometry")
        raise ErroLeitura(f"campo identificador '{campo_id}' ausente em talhões. Campos: {campos}")
    verificar_crs({"ortomosaico": crs_ref, "talhoes": gdf.crs})
    ids, utils = [], []
    for _, linha in gdf.iterrows():
        geom, ident = linha.geometry, str(linha[campo_id])
        if geom is None or geom.is_empty or not isinstance(geom, (Polygon, MultiPolygon)) or not geom.is_valid:
            raise ErroContrato(f"talhão {ident!r}: geometria vazia, inválida ou não poligonal")
        util = geom.buffer(-buffer_interno_m)
        if util.is_empty:
            raise ErroContrato(f"talhão {ident!r}: área útil vazia após buffer interno de {buffer_interno_m} m")
        ids.append(ident)
        utils.append(util)
    if not ids:
        raise ErroContrato("a camada de talhões está vazia")
    if len(set(ids)) != len(ids):
        raise ErroContrato("id duplicado em talhões")
    return Talhoes(ids=tuple(ids), poligonos_util=tuple(utils), uniao_util=unary_union(utils))


# ---------------------------------------------------------------- grade

@dataclass(frozen=True)
class Grade:
    transform: Affine
    largura: int
    altura: int
    res: float

    def bounds_janela(self, lin0: int, col0: int, h: int, w: int) -> tuple[float, float, float, float]:
        x0, y1 = self.transform * (col0, lin0)
        return (x0, y1 - h * self.res, x0 + w * self.res, y1)

    def transform_janela(self, lin0: int, col0: int) -> Affine:
        x0, y1 = self.transform * (col0, lin0)
        return from_origin(x0, y1, self.res, self.res)

    def faixa_pixels(self, bounds: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        """(lin0, col0, lin1, col1) da grade que cobre `bounds`, recortado à grade."""
        x0, y0 = self.transform.c, self.transform.f
        c0 = max(0, int(math.floor((bounds[0] - x0) / self.res)))
        c1 = min(self.largura, int(math.ceil((bounds[2] - x0) / self.res)))
        l0 = max(0, int(math.floor((y0 - bounds[3]) / self.res)))
        l1 = min(self.altura, int(math.ceil((y0 - bounds[1]) / self.res)))
        return l0, c0, l1, c1

    def janelas(self, bounds: tuple[float, float, float, float], lado: int) -> Iterator[tuple[int, int, int, int]]:
        """(lin0, col0, h, w) em blocos de `lado` pixels sobre a parte da grade que cobre `bounds`."""
        l0, c0, l1, c1 = self.faixa_pixels(bounds)
        l0, c0 = (l0 // BLOCO_TIFF) * BLOCO_TIFF, (c0 // BLOCO_TIFF) * BLOCO_TIFF  # alinha aos blocos do GeoTIFF
        for lin in range(l0, l1, lado):
            for col in range(c0, c1, lado):
                yield lin, col, min(lado, l1 - lin), min(lado, c1 - col)


class Ortomosaico:
    """Leitor do ortomosaico RGB por janelas, na grade de trabalho (redução por média de área)."""

    def __init__(self, caminho: Path, bandas_rgb: tuple[int, int, int], resolucao_m: float) -> None:
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ErroLeitura(f"ortomosaico não encontrado: {caminho}")
        try:
            self._ds = rasterio.open(caminho)
        except rasterio.errors.RasterioIOError as exc:
            raise ErroLeitura(f"não foi possível abrir o ortomosaico {caminho}: {exc}") from exc
        t = self._ds.transform
        if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
            self._ds.close()
            raise ErroContrato("ortomosaico com transformação rotacionada ou invertida não é suportado")
        faltam = [b for b in bandas_rgb if b > self._ds.count]
        if faltam:
            self._ds.close()
            raise ErroContrato(f"banda(s) {faltam} não existe(m): o ortomosaico tem {self._ds.count}")
        nativa = float(min(abs(t.a), abs(t.e)))
        if resolucao_m < nativa * (1 - 1e-6):
            self._ds.close()
            raise ErroConfig(f"resolucao_trabalho_m={resolucao_m} menor que a resolução nativa {nativa:.4f} m")
        self.crs = self._ds.crs
        self.bandas = list(bandas_rgb)
        b = self._ds.bounds
        self.bounds = (b.left, b.bottom, b.right, b.top)
        self.grade = Grade(transform=from_origin(b.left, b.top, resolucao_m, resolucao_m),
                           largura=int(math.ceil((b.right - b.left) / resolucao_m - 1e-9)),
                           altura=int(math.ceil((b.top - b.bottom) / resolucao_m - 1e-9)),
                           res=resolucao_m)

    def ler(self, lin0: int, col0: int, h: int, w: int, borda: int = 0) -> tuple[np.ndarray, np.ndarray]:
        """Bandas (3, h+2b, w+2b) float32 e validade (h+2b, w+2b) bool da janela com borda `borda`.
        Fora do ortomosaico: zero e inválido."""
        g = self.grade
        lin0, col0, h, w = lin0 - borda, col0 - borda, h + 2 * borda, w + 2 * borda
        bx0, by0, bx1, by1 = g.bounds_janela(lin0, col0, h, w)
        rx0, ry0, rx1, ry1 = self.bounds
        x0, y0, x1, y1 = max(bx0, rx0), max(by0, ry0), min(bx1, rx1), min(by1, ry1)
        dados = np.zeros((3, h, w), dtype=np.float32)
        valido = np.zeros((h, w), dtype=bool)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return dados, valido
        dc0 = int(round((x0 - bx0) / g.res))
        dl0 = int(round((by1 - y1) / g.res))
        wc = max(1, min(w - dc0, int(round((x1 - x0) / g.res))))
        hc = max(1, min(h - dl0, int(round((y1 - y0) / g.res))))
        janela = from_bounds(x0, y0, x1, y1, transform=self._ds.transform)
        lido = self._ds.read(self.bandas, window=janela, out_shape=(3, hc, wc),
                             resampling=Resampling.average).astype(np.float32)
        masc = self._ds.read_masks(self.bandas, window=janela, out_shape=(3, hc, wc),
                                   resampling=Resampling.average)
        dados[:, dl0:dl0 + hc, dc0:dc0 + wc] = lido
        valido[dl0:dl0 + hc, dc0:dc0 + wc] = (masc >= 128).all(axis=0)
        return dados, valido

    def fechar(self) -> None:
        self._ds.close()


def mascara_poligono(geom, grade: Grade, lin0: int, col0: int, h: int, w: int) -> np.ndarray:
    """True dentro de `geom` na janela (centro do pixel)."""
    bx = box(*grade.bounds_janela(lin0, col0, h, w))
    recorte = geom.intersection(bx) if geom is not None else None
    if recorte is None or recorte.is_empty:
        return np.zeros((h, w), dtype=bool)
    return ~geometry_mask([recorte], out_shape=(h, w), transform=grade.transform_janela(lin0, col0))


def criar_geotiff(caminho: Path, grade: Grade, crs, dtype: str, nodata=None) -> rasterio.io.DatasetWriter:
    """GeoTIFF de uma banda, em blocos, comprimido, na grade de trabalho e no CRS da entrada."""
    caminho = Path(caminho)
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        return rasterio.open(
            caminho, "w", driver="GTiff", width=grade.largura, height=grade.altura, count=1, dtype=dtype,
            crs=crs, transform=grade.transform, nodata=nodata, tiled=True, blockxsize=BLOCO_TIFF, blockysize=BLOCO_TIFF,
            compress="deflate", BIGTIFF="IF_SAFER")
    except Exception as exc:
        raise ErroLeitura(f"não foi possível criar {caminho}: {exc}") from exc
