"""Módulo saida: grava o GeoPackage com as camadas linhas_corrigidas e estacoes
(docs/interfaces-fase1.md, seções 2.2 e 6.8). Mesmo CRS da entrada."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import Point

from .tipos import STATUS_VALIDOS, ErroContrato, ErroLeitura, ResultadoPassada

CAMADA_LINHAS = "linhas_corrigidas"
CAMADA_ESTACOES = "estacoes"


def gravar_geopackage(resultados: list[ResultadoPassada], crs: CRS, caminho_saida: Path) -> None:
    """Grava as camadas linhas_corrigidas e estacoes (seção 2.2) no CRS da entrada.

    Convenção do sinal: desvio_m positivo quando o eixo real está à esquerda da linha projetada,
    no sentido de digitalização. Geometria da estação: ponto da linha projetada deslocado por
    desvio_m (na posição projetada se nulo).

    Raises:
        ErroLeitura: o caminho não é gravável.
        ErroContrato: sem resultados ou status fora do conjunto permitido.
    """
    if not resultados:
        raise ErroContrato("nenhum resultado para gravar")
    caminho_saida = Path(caminho_saida)

    linhas = []
    estacoes = []
    for r in resultados:
        for e in r.estacoes:
            if e.status not in STATUS_VALIDOS:
                raise ErroContrato(f"status inválido na saída: {e.status!r}; permitidos: {', '.join(STATUS_VALIDOS)}")
            if e.desvio_m is None:
                ponto = Point(e.x, e.y)
            else:
                ponto = Point(e.x + e.desvio_m * e.normal_esq[0], e.y + e.desvio_m * e.normal_esq[1])
            estacoes.append({
                "id_passada": e.id_passada, "talhao": e.talhao, "estacao_m": float(e.estacao_m),
                "desvio_m": None if e.desvio_m is None else float(e.desvio_m),
                "status": e.status, "confianca": float(e.confianca), "geometry": ponto,
            })
        linhas.append({
            "id_passada": r.passada.id_passada, "talhao": r.passada.talhao, "n_estacoes": len(r.estacoes),
            "frac_duvidosa": float(r.frac_duvidosa), "frac_interpolada": float(r.frac_interpolada),
            "revisao_manual": bool(r.revisao_manual), "geometry": r.linha_corrigida,
        })

    gdf_linhas = gpd.GeoDataFrame(linhas, geometry="geometry", crs=crs)
    gdf_est = gpd.GeoDataFrame(estacoes, geometry="geometry", crs=crs)
    try:
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        gdf_linhas.to_file(caminho_saida, layer=CAMADA_LINHAS, driver="GPKG")
        gdf_est.to_file(caminho_saida, layer=CAMADA_ESTACOES, driver="GPKG")
    except OSError as exc:
        raise ErroLeitura(f"não foi possível gravar {caminho_saida}: {exc}") from exc
    except Exception as exc:  # erros de gravação do GDAL/pyogrio
        raise ErroLeitura(f"não foi possível gravar {caminho_saida}: {exc}") from exc
