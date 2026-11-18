"""Comparação das fileiras detectadas com linhas de referência (docs/interfaces-deteccao.md, seção 6.9).

A referência é SECUNDÁRIA (linhas recebidas, não RTK): a comparação mede concordância, não acurácia.
Módulo independente da detecção: importa só entrada.verificar_crs e tipos.
DESVIO das interfaces: gravar_diferencas recebe também o caminho da referência e a configuração, porque o
relatório agregado não guarda as distâncias por trecho.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely import STRtree
from shapely.geometry import LineString, Point

from .config import ConfigComparacao
from .entrada import verificar_crs
from .tipos import ErroContrato, ErroDeteccao, ErroLeitura

AVISO = "Referência secundária, não é RTK; não mede acurácia."
EXTENSOES = {".gpkg", ".shp"}
PASSO_TANGENTE_M = 5.0
PASSO_COBERTURA_M = 1.0


@dataclass(frozen=True)
class EstatisticaDistancia:
    n: int
    media_abs_m: float | None
    mediana_abs_m: float | None
    p95_abs_m: float | None
    vies_m: float | None  # média com sinal; + quando a fileira detectada está à esquerda da referência


@dataclass(frozen=True)
class RelatorioComparacao:
    aviso: str
    n_trechos: int
    taxa_pareamento: float
    cobertura_referencia: float
    global_: EstatisticaDistancia
    por_status: dict[str, EstatisticaDistancia]
    por_fileira: dict[str, EstatisticaDistancia]


def _estatistica(valores: list[float]) -> EstatisticaDistancia:
    if not valores:
        return EstatisticaDistancia(0, None, None, None, None)
    v = np.asarray(valores, dtype=float)
    a = np.abs(v)
    return EstatisticaDistancia(int(v.size), float(a.mean()), float(np.median(a)),
                                float(np.percentile(a, 95)), float(v.mean()))


def _ler(caminho: Path, rotulo: str, layer: str | None = None) -> gpd.GeoDataFrame:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroLeitura(f"arquivo de {rotulo} não encontrado: {caminho}")
    if caminho.suffix.lower() not in EXTENSOES:
        raise ErroLeitura(f"formato de {rotulo} não suportado ({caminho.suffix}); use .gpkg ou .shp")
    try:
        return gpd.read_file(caminho, layer=layer) if layer else gpd.read_file(caminho)
    except Exception as exc:
        raise ErroLeitura(f"não foi possível ler {rotulo} em {caminho}: {exc}") from exc


def carregar_referencia(caminho: Path, crs_esperado: CRS, cfg: ConfigComparacao) -> tuple[LineString, ...]:
    """Raises: ErroLeitura; ErroCRS (divergente do CRS das fileiras, sem reprojetar);
    ErroContrato (geometria não-linha, vazia ou inválida)."""
    gdf = _ler(caminho, "referência")
    if cfg.campo_id_referencia and cfg.campo_id_referencia not in gdf.columns:
        raise ErroLeitura(f"campo '{cfg.campo_id_referencia}' ausente na referência")
    verificar_crs({"fileiras": crs_esperado, "referencia": CRS.from_user_input(gdf.crs) if gdf.crs else None})
    linhas: list[LineString] = []
    for i, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty:
            raise ErroContrato(f"referência: feição {i} com geometria vazia")
        if not isinstance(geom, LineString):
            raise ErroContrato(f"referência: feição {i} não é LineString simples ({geom.geom_type})")
        if not geom.is_valid:
            raise ErroContrato(f"referência: feição {i} com geometria inválida")
        linhas.append(geom)
    if not linhas:
        raise ErroContrato("a camada de referência está vazia")
    return tuple(linhas)


def _indice(referencia: tuple[LineString, ...]) -> STRtree:
    return STRtree(list(referencia))


def distancia_lateral(ponto_x: float, ponto_y: float, direcao: tuple[float, float],
                      referencia: tuple[LineString, ...], cfg: ConfigComparacao,
                      _arvore: STRtree | None = None) -> float | None:
    """Distância com sinal medida na normal à esquerda de `direcao`, da linha de referência mais próxima
    (na normal) até o ponto, dentro de cfg.distancia_max_pareamento_m. Positiva quando o ponto detectado
    está à esquerda da referência. None se não houver (trecho não pareado)."""
    ux, uy = direcao
    norma = float(np.hypot(ux, uy))
    if norma == 0:
        return None
    nx, ny = -uy / norma, ux / norma
    d = cfg.distancia_max_pareamento_m
    corte = LineString([(ponto_x - nx * d, ponto_y - ny * d), (ponto_x + nx * d, ponto_y + ny * d)])
    arvore = _arvore or _indice(referencia)
    melhor: float | None = None
    for i in arvore.query(corte, predicate="intersects"):
        inter = referencia[int(i)].intersection(corte)
        if inter.is_empty:
            continue
        for p in getattr(inter, "geoms", [inter]):
            if not isinstance(p, Point):
                continue
            off = (p.x - ponto_x) * nx + (p.y - ponto_y) * ny  # posição da referência na normal à esquerda
            dist = -off  # + quando o ponto está à esquerda da referência
            if abs(dist) <= d and (melhor is None or abs(dist) < abs(melhor)):
                melhor = float(dist)
    return melhor


def _direcao(geom: LineString, pos: float) -> tuple[float, float]:
    comp = geom.length
    a = geom.interpolate(max(0.0, pos - PASSO_TANGENTE_M))
    b = geom.interpolate(min(comp, pos + PASSO_TANGENTE_M))
    return (b.x - a.x, b.y - a.y)


def medir_trechos(caminho_fileiras: Path, caminho_referencia: Path, cfg: ConfigComparacao
                  ) -> tuple[gpd.GeoDataFrame, tuple[LineString, ...], gpd.GeoDataFrame]:
    """Devolve (trechos com coluna distancia_m [NaN = não pareado], referência, fileiras)."""
    fil = _ler(caminho_fileiras, "fileiras", "fileiras")
    tre = _ler(caminho_fileiras, "trechos", "trechos")
    if fil.empty or tre.empty:
        raise ErroDeteccao("a camada de fileiras está vazia: nada a comparar")
    crs = CRS.from_user_input(fil.crs) if fil.crs else None
    ref = carregar_referencia(caminho_referencia, crs, cfg) if crs is not None else carregar_referencia(
        caminho_referencia, CRS.from_epsg(31983), cfg)
    geoms = dict(zip(fil["id_fileira"], fil.geometry))
    arvore = _indice(ref)
    dist = []
    for _, r in tre.iterrows():
        g = geoms[r["id_fileira"]]
        d = distancia_lateral(r.geometry.x, r.geometry.y, _direcao(g, float(r["posicao_m"])), ref, cfg, arvore)
        dist.append(np.nan if d is None else d)
    tre = tre.copy()
    tre["distancia_m"] = dist
    return tre, ref, fil


def comparar(caminho_fileiras: Path, caminho_referencia: Path, cfg: ConfigComparacao) -> RelatorioComparacao:
    """Mede, por trecho, a distância lateral à referência e agrega. Não altera nenhuma camada.

    cobertura_referencia: fração do comprimento da referência (amostrada a cada 1 m) a no máximo
    cfg.distancia_max_pareamento_m de alguma fileira detectada.
    Raises: ErroLeitura, ErroCRS, ErroContrato; ErroDeteccao se a camada de fileiras estiver vazia."""
    tre, ref, fil = medir_trechos(caminho_fileiras, caminho_referencia, cfg)
    pareado = tre["distancia_m"].notna()
    usar = tre["status"].isin(cfg.usar_status)
    glob = [float(v) for v in tre.loc[pareado & usar, "distancia_m"]]
    por_status = {s: _estatistica([float(v) for v in tre.loc[pareado & (tre["status"] == s), "distancia_m"]])
                  for s in sorted(tre["status"].unique())}
    por_fileira = {i: _estatistica([float(v) for v in tre.loc[pareado & usar & (tre["id_fileira"] == i), "distancia_m"]])
                   for i in sorted(tre["id_fileira"].unique())}
    arv_f = STRtree(list(fil.geometry))
    cobertos = total = 0.0
    for linha in ref:
        n = max(1, int(np.ceil(linha.length / PASSO_COBERTURA_M)))
        for k in range(n):
            p = linha.interpolate((k + 0.5) * linha.length / n)
            total += 1
            idx = arv_f.nearest(p)
            if idx is not None and fil.geometry.iloc[int(idx)].distance(p) <= cfg.distancia_max_pareamento_m:
                cobertos += 1
    return RelatorioComparacao(
        aviso=AVISO, n_trechos=int(len(tre)), taxa_pareamento=float(pareado.mean()),
        cobertura_referencia=float(cobertos / total) if total else 0.0,
        global_=_estatistica(glob), por_status=por_status, por_fileira=por_fileira)


def gravar_diferencas(caminho_fileiras: Path, caminho_referencia: Path, cfg: ConfigComparacao,
                      caminho_saida: Path) -> None:
    """Opcional. Camada de pontos 'diferencas' com a distância lateral por trecho (vazio = não pareado)."""
    tre, _, _ = medir_trechos(caminho_fileiras, caminho_referencia, cfg)
    try:
        p = Path(caminho_saida)
        if p.exists():
            p.unlink()
        tre.to_file(p, layer="diferencas", driver="GPKG")
    except Exception as exc:
        raise ErroLeitura(f"não foi possível gravar {caminho_saida}: {exc}") from exc
