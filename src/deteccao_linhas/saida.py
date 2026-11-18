"""Numeração das fileiras e GeoPackage de saída (docs/interfaces-deteccao.md, seção 6.8)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.geometry import Point

from .tipos import STATUS_VALIDOS, ErroContrato, ErroLeitura, Fileira, FileiraAvaliada


def numerar_fileiras(avaliadas: list[FileiraAvaliada], u_ref: tuple[float, float],
                     c_ref: tuple[float, float]) -> list[Fileira]:
    """Ordem crescente da mediana de t_g = dot(p - c_ref, n_ref), n_ref = normal à esquerda de u_ref;
    id 'talhao-F0001'. A numeração é por talhão e é só chave de ordem (em curvas a ordem pode trocar)."""
    nx, ny = -u_ref[1], u_ref[0]
    por_talhao: dict[str, list[tuple[float, FileiraAvaliada]]] = {}
    for f in avaliadas:
        tg = [(p.x - c_ref[0]) * nx + (p.y - c_ref[1]) * ny for p in f.pontos]
        por_talhao.setdefault(f.talhao, []).append((float(np.median(tg)), f))
    saida: list[Fileira] = []
    for talhao, lista in por_talhao.items():
        lista.sort(key=lambda e: e[0])
        for n, (_, f) in enumerate(lista, start=1):
            saida.append(Fileira(id_fileira=f"{talhao}-F{n:04d}", avaliada=f))
    return saida


def gravar_geopackage(fileiras: list[Fileira], crs: CRS, caminho_saida: Path) -> None:
    """Grava as camadas `fileiras` (linha) e `trechos` (ponto, um por bloco e fileira) no CRS da entrada.

    Raises: ErroLeitura (caminho não gravável); ErroContrato (status fora do conjunto).
    """
    caminho_saida = Path(caminho_saida)
    for f in fileiras:
        for p in f.avaliada.pontos:
            if p.status not in STATUS_VALIDOS:
                raise ErroContrato(f"status inválido {p.status!r} na fileira {f.id_fileira}")
    linhas = gpd.GeoDataFrame(
        {"id_fileira": [f.id_fileira for f in fileiras],
         "talhao": [f.avaliada.talhao for f in fileiras],
         "comprimento_m": [f.avaliada.comprimento_m for f in fileiras],
         "confianca_media": [f.avaliada.confianca_media for f in fileiras],
         "frac_duvidosa": [f.avaliada.frac_duvidosa for f in fileiras]},
        geometry=[f.avaliada.geometria for f in fileiras], crs=crs)
    pts = [(f.id_fileira, p) for f in fileiras for p in f.avaliada.pontos]
    trechos = gpd.GeoDataFrame(
        {"id_fileira": [i for i, _ in pts], "posicao_m": [p.posicao_m for _, p in pts],
         "status": [p.status for _, p in pts], "confianca": [p.confianca for _, p in pts]},
        geometry=[Point(p.x, p.y) for _, p in pts], crs=crs)
    try:
        if caminho_saida.exists():
            caminho_saida.unlink()
        linhas.to_file(caminho_saida, layer="fileiras", driver="GPKG")
        trechos.to_file(caminho_saida, layer="trechos", driver="GPKG", mode="a")
    except Exception as exc:  # pyogrio levanta tipos variados
        raise ErroLeitura(f"não foi possível gravar {caminho_saida}: {exc}") from exc
