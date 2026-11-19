"""Módulo entrada: leitura e validação do contrato (docs/interfaces-deteccao.md, seção 6.1).

Não reprojeta e não comenta qualidade ou georreferenciamento do ortomosaico.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import rasterio
from pyproj import CRS
from shapely.geometry import MultiPolygon, Polygon

from .config import Config
from .tipos import DadosEntrada, ErroContrato, ErroCRS, ErroLeitura, Talhao

EXTENSOES_VETORIAIS = {".gpkg", ".shp"}


def _rotulo_crs(crs: CRS) -> str:
    auth = crs.to_authority()
    return f"{auth[0]}:{auth[1]}" if auth else crs.name


def _sem_towgs84_nulo(crs: CRS) -> CRS:
    """Remove só uma transformação TOWGS84 com todos os parâmetros nulos (aparece em alguns .prj/GeoTIFF
    e faz o pyproj tratar o CRS como "amarrado", diferente do EPSG igual). Transformação não nula é mantida,
    portanto continua contando como divergência. Não reprojeta nada."""
    if not crs.is_bound:
        return crs
    params = crs.to_json_dict().get("transformation", {}).get("parameters", [])
    if params and all(float(p.get("value", 1.0)) == 0.0 for p in params):
        return crs.source_crs
    return crs


def verificar_crs(camadas: dict[str, CRS | None]) -> None:
    """Compara por equivalência (CRS.equals). O primeiro item é a referência. Não reprojeta.

    Raises:
        ErroCRS: CRS ausente, divergência (todas as camadas listadas, e quais divergem do
            primeiro item) ou CRS não projetado em metros.
    """
    ausentes = [n for n, c in camadas.items() if c is None]
    if ausentes:
        raise ErroCRS(f"CRS ausente em: {', '.join(ausentes)}. Defina o CRS dessas camadas antes de rodar.")
    nomes = list(camadas)
    ref_nome = nomes[0]
    ref = _sem_towgs84_nulo(camadas[ref_nome])
    divergentes = [n for n in nomes[1:] if not _sem_towgs84_nulo(camadas[n]).equals(ref)]
    if divergentes:
        lista = "; ".join(f"{n}={_rotulo_crs(c)}" for n, c in camadas.items())
        raise ErroCRS(
            f"CRS divergente: {lista}. Divergem do {ref_nome}: {', '.join(divergentes)}. "
            "Reprojete as camadas antes de rodar."
        )
    for nome, crs in ((n, _sem_towgs84_nulo(c)) for n, c in camadas.items()):
        unidade = crs.axis_info[0].unit_name.lower() if crs.axis_info else ""
        if not crs.is_projected or unidade not in ("metre", "meter"):
            raise ErroCRS(f"CRS de {nome} ({_rotulo_crs(crs)}) não é projetado em metros.")


def _ler_vetor(caminho: Path, rotulo: str) -> gpd.GeoDataFrame:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroLeitura(f"arquivo de {rotulo} não encontrado: {caminho}")
    if caminho.suffix.lower() not in EXTENSOES_VETORIAIS:
        raise ErroLeitura(f"formato de {rotulo} não suportado ({caminho.suffix}); use .gpkg ou .shp")
    try:
        return gpd.read_file(caminho)
    except Exception as exc:
        raise ErroLeitura(f"não foi possível ler {rotulo} em {caminho}: {exc}") from exc


def carregar_entrada(caminho_ortomosaico: Path, caminho_talhoes: Path, cfg: Config) -> DadosEntrada:
    """Lê metadados do raster e os talhões; valida o contrato.

    Raises:
        ErroLeitura: arquivo inexistente, formato não suportado, campo identificador ausente.
        ErroCRS: CRS ausente, não projetado em metros ou divergente entre raster e talhões.
        ErroContrato: talhão não-polígono, vazio ou inválido, id duplicado, banda inexistente.
    """
    caminho_ortomosaico = Path(caminho_ortomosaico)
    if not caminho_ortomosaico.is_file():
        raise ErroLeitura(f"ortomosaico não encontrado: {caminho_ortomosaico}")
    try:
        with rasterio.open(caminho_ortomosaico) as ds:
            crs_raster = CRS.from_user_input(ds.crs) if ds.crs else None
            n_bandas = ds.count
    except rasterio.errors.RasterioIOError as exc:
        raise ErroLeitura(f"não foi possível abrir o ortomosaico {caminho_ortomosaico}: {exc}") from exc

    gdf = _ler_vetor(caminho_talhoes, "talhões")
    if cfg.campo_id_talhao not in gdf.columns:
        campos = ", ".join(c for c in gdf.columns if c != "geometry")
        raise ErroLeitura(f"campo identificador '{cfg.campo_id_talhao}' ausente em talhões. Campos: {campos}")

    verificar_crs({
        "ortomosaico": crs_raster,
        "talhoes": CRS.from_user_input(gdf.crs) if gdf.crs else None,
    })

    ausentes = [b for b in cfg.bandas_rgb if b > n_bandas]
    if ausentes:
        raise ErroContrato(f"banda(s) {ausentes} indicada(s) na configuração não existe(m): o raster tem {n_bandas}")

    talhoes: list[Talhao] = []
    for _, linha in gdf.iterrows():
        geom = linha.geometry
        ident = linha[cfg.campo_id_talhao]
        if geom is None or geom.is_empty:
            raise ErroContrato(f"talhão {ident!r} com geometria vazia")
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise ErroContrato(f"talhão {ident!r} não é polígono ({geom.geom_type})")
        if not geom.is_valid:
            raise ErroContrato(f"talhão {ident!r} com geometria inválida")
        talhoes.append(Talhao(id=str(ident), poligono=geom))
    if not talhoes:
        raise ErroContrato("a camada de talhões está vazia")
    ids = [t.id for t in talhoes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ErroContrato(f"id duplicado em talhões: {', '.join(dup)}")

    return DadosEntrada(caminho_ortomosaico=caminho_ortomosaico, crs=crs_raster, talhoes=tuple(talhoes))
