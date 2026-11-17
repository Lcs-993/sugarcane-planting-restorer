"""Módulo entrada: leitura e validação do contrato de dados (docs/interfaces-fase1.md, seção 6.1).

Não reprojeta nada e não comenta qualidade ou georreferenciamento do ortomosaico.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import rasterio
from pyproj import CRS
from shapely.geometry import LineString, MultiPolygon, Polygon

from .config import Config
from .tipos import (
    DadosEntrada,
    ErroContrato,
    ErroCRS,
    ErroLeitura,
    Passada,
    Talhao,
)

EXTENSOES_VETORIAIS = {".gpkg", ".shp"}


def _rotulo_crs(crs: CRS) -> str:
    auth = crs.to_authority()
    return f"{auth[0]}:{auth[1]}" if auth else crs.name


def verificar_crs(camadas: dict[str, CRS | None]) -> None:
    """Compara os CRS (ex.: {"ortomosaico": ..., "talhoes": ..., "linhas": ...}).

    O primeiro item é a referência. Não reprojeta.

    Raises:
        ErroCRS: CRS ausente em alguma camada, divergência entre camadas (todas listadas, com as
            que divergem da referência) ou CRS não projetado em metros.
    """
    ausentes = [nome for nome, crs in camadas.items() if crs is None]
    if ausentes:
        raise ErroCRS(f"CRS ausente em: {', '.join(ausentes)}. Defina o CRS dessas camadas antes de rodar.")
    nomes = list(camadas)
    ref_nome = nomes[0]
    ref = camadas[ref_nome]
    divergentes = [n for n in nomes[1:] if not camadas[n].equals(ref)]
    if divergentes:
        lista = "; ".join(f"{n}={_rotulo_crs(c)}" for n, c in camadas.items())
        raise ErroCRS(
            f"CRS divergente: {lista}. Divergem do {ref_nome}: {', '.join(divergentes)}. "
            "Reprojete as camadas antes de rodar."
        )
    for nome, crs in camadas.items():
        unidade = crs.axis_info[0].unit_name.lower() if crs.axis_info else ""
        if not crs.is_projected or unidade not in ("metre", "meter"):
            raise ErroCRS(
                f"CRS de {nome} ({_rotulo_crs(crs)}) não é projetado em metros. "
                "Use um CRS projetado em metros nas três entradas."
            )


def atribuir_talhao(linha: LineString, talhoes: tuple[Talhao, ...]) -> str:
    """Devolve o id do talhão que contém a linha por inteiro.

    Raises:
        ErroContrato: a linha não cai em nenhum talhão (ou só parcialmente), ou cai em mais de um.
    """
    contem = [t.id for t in talhoes if t.poligono.covers(linha)]
    if not contem:
        raise ErroContrato("linha fora de qualquer talhão (ou só parcialmente contida em um talhão)")
    if len(contem) > 1:
        raise ErroContrato(f"linha contida em mais de um talhão: {', '.join(contem)}")
    return contem[0]


def _ler_vetor(caminho: Path, rotulo: str) -> gpd.GeoDataFrame:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroLeitura(f"arquivo de {rotulo} não encontrado: {caminho}")
    if caminho.suffix.lower() not in EXTENSOES_VETORIAIS:
        raise ErroLeitura(
            f"formato de {rotulo} não suportado ({caminho.suffix}); use GeoPackage (.gpkg) ou shapefile (.shp)"
        )
    try:
        return gpd.read_file(caminho)
    except Exception as exc:  # leitura do GDAL/pyogrio pode levantar vários tipos
        raise ErroLeitura(f"não foi possível ler {rotulo} em {caminho}: {exc}") from exc


def _exigir_campo(gdf: gpd.GeoDataFrame, campo: str, rotulo: str) -> None:
    if campo not in gdf.columns:
        raise ErroLeitura(
            f"campo identificador '{campo}' ausente em {rotulo}. Campos disponíveis: "
            f"{', '.join(c for c in gdf.columns if c != 'geometry')}"
        )


def _ids_unicos(valores: list[str], rotulo: str) -> None:
    vistos: set[str] = set()
    dup = {v for v in valores if v in vistos or vistos.add(v)}
    if dup:
        raise ErroContrato(f"id duplicado em {rotulo}: {', '.join(sorted(dup))}")


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
            no raster, linha fora de qualquer talhão.
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

    gdf_t = _ler_vetor(caminho_talhoes, "talhões")
    gdf_l = _ler_vetor(caminho_linhas, "linhas")
    _exigir_campo(gdf_t, cfg.campo_id_talhao, "talhões")
    _exigir_campo(gdf_l, cfg.campo_id_passada, "linhas")

    verificar_crs({
        "ortomosaico": crs_raster,
        "talhoes": CRS.from_user_input(gdf_t.crs) if gdf_t.crs else None,
        "linhas": CRS.from_user_input(gdf_l.crs) if gdf_l.crs else None,
    })

    bandas = list(cfg.bandas_rgb) + ([cfg.banda_nir] if cfg.banda_nir is not None else [])
    ausentes = [b for b in bandas if b > n_bandas]
    if ausentes:
        raise ErroContrato(f"banda(s) {ausentes} indicada(s) na configuração não existe(m): o raster tem {n_bandas} banda(s)")

    talhoes: list[Talhao] = []
    for _, linha in gdf_t.iterrows():
        geom = linha.geometry
        if geom is None or geom.is_empty:
            raise ErroContrato("talhão com geometria vazia")
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise ErroContrato(f"talhão {linha[cfg.campo_id_talhao]!r} não é polígono ({geom.geom_type})")
        if not geom.is_valid:
            raise ErroContrato(f"talhão {linha[cfg.campo_id_talhao]!r} com geometria inválida")
        talhoes.append(Talhao(id=str(linha[cfg.campo_id_talhao]), poligono=geom))
    if not talhoes:
        raise ErroContrato("a camada de talhões está vazia")
    _ids_unicos([t.id for t in talhoes], "talhões")

    brutas: list[tuple[str, LineString]] = []
    for _, linha in gdf_l.iterrows():
        geom = linha.geometry
        ident = linha[cfg.campo_id_passada]
        if geom is None or geom.is_empty:
            raise ErroContrato(f"passada {ident!r} com geometria vazia")
        if not isinstance(geom, LineString):
            raise ErroContrato(f"passada {ident!r} não é LineString simples ({geom.geom_type})")
        if not geom.is_valid:
            raise ErroContrato(f"passada {ident!r} com geometria inválida")
        brutas.append((str(ident), geom))
    if not brutas:
        raise ErroContrato("a camada de linhas está vazia")
    _ids_unicos([i for i, _ in brutas], "linhas")

    talhoes_t = tuple(talhoes)
    passadas: list[Passada] = []
    for ident, geom in brutas:
        try:
            tid = atribuir_talhao(geom, talhoes_t)
        except ErroContrato as exc:
            raise ErroContrato(f"passada {ident!r}: {exc}") from exc
        passadas.append(Passada(id_passada=ident, talhao=tid, geometria=geom))

    return DadosEntrada(
        caminho_ortomosaico=caminho_ortomosaico,
        crs=crs_raster,
        talhoes=talhoes_t,
        passadas=tuple(passadas),
    )
