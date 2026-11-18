"""Blocos orientados e perfil lateral de vegetação (docs/interfaces-deteccao.md, seção 6.4).

H1 (hipótese, sem fonte lida): integrar a vegetação ao longo de blocos longos (cfg.comprimento_bloco_m)
em bins laterais concentra as fileiras descontínuas num pico mensurável.
DESVIO das interfaces: Bloco ganhou `poligono` (bloco recortado pela região, em coordenadas do mapa),
para que regiões vizinhas não contem o mesmo pixel duas vezes; s0_m e comprimento_m descrevem o
trecho realmente coberto pelo polígono.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from rasterio.features import geometry_mask
from shapely.geometry import Polygon

from .config import Config
from .indice_binarizacao import FonteBinaria
from .tipos import Bloco, ErroContrato, PerfilLateral, Regiao

COMPRIMENTO_MIN_BLOCO_M = 2.0  # sobras de borda menores que isto não formam bloco


def _coords(geom) -> np.ndarray:
    return shapely.get_coordinates(geom)


def gerar_blocos(regioes: list[Regiao], u_ref: tuple[float, float], c_ref: tuple[float, float],
                 cfg: Config) -> list[Bloco]:
    """Blocos retangulares orientados por região, recortados pelo polígono da região.

    Ordenados por s_global_m crescente. Regiões sem direção são ignoradas (erro de contrato).
    """
    blocos: list[Bloco] = []
    for reg in regioes:
        if reg.direcao is None:
            raise ErroContrato(f"região {reg.id_regiao} sem direção; rode estimar_direcoes antes")
        ux, uy = reg.direcao.vetor
        nx, ny = -uy, ux
        cx, cy = reg.poligono.centroid.coords[0]
        pts = _coords(reg.poligono)
        s_all = (pts[:, 0] - cx) * ux + (pts[:, 1] - cy) * uy
        t_all = (pts[:, 0] - cx) * nx + (pts[:, 1] - cy) * ny
        smin, smax, tmin, tmax = s_all.min(), s_all.max(), t_all.min(), t_all.max()
        n = 0
        s0 = smin
        while s0 < smax - 1e-9:
            s1 = min(s0 + cfg.comprimento_bloco_m, smax)
            ret = Polygon([(cx + s * ux + t * nx, cy + s * uy + t * ny)
                           for s, t in ((s0, tmin), (s1, tmin), (s1, tmax), (s0, tmax))])
            poli = ret.intersection(reg.poligono)
            s0 += cfg.passo_bloco_m
            if poli.is_empty or poli.area <= 0:
                continue
            if poli.geom_type == "GeometryCollection":
                partes = [g for g in poli.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                if not partes:
                    continue
                poli = shapely.union_all(partes)
            p = _coords(poli)
            sp = (p[:, 0] - cx) * ux + (p[:, 1] - cy) * uy
            tp = (p[:, 0] - cx) * nx + (p[:, 1] - cy) * ny
            bs0, bs1, bt0, bt1 = sp.min(), sp.max(), tp.min(), tp.max()
            if bs1 - bs0 < COMPRIMENTO_MIN_BLOCO_M or bt1 - bt0 < cfg.lateral_minima_bloco_m:
                continue
            n += 1
            sc = (bs0 + bs1) / 2.0
            tc = (bt0 + bt1) / 2.0
            centro = (cx + sc * ux + tc * nx, cy + sc * uy + tc * ny)
            s_glob = (centro[0] - c_ref[0]) * u_ref[0] + (centro[1] - c_ref[1]) * u_ref[1]
            blocos.append(Bloco(
                id_bloco=f"{reg.id_regiao}-B{n:03d}", id_regiao=reg.id_regiao, origem=(cx, cy),
                u=(ux, uy), n=(nx, ny), s0_m=float(bs0), comprimento_m=float(bs1 - bs0),
                t_min_m=float(bt0), t_max_m=float(bt1), s_global_m=float(s_glob), poligono=poli))
    blocos.sort(key=lambda b: (b.s_global_m, b.id_bloco))
    return blocos


def calcular_perfil(fonte: FonteBinaria, bloco: Bloco, cfg: Config) -> PerfilLateral:
    """Integra a vegetação ao longo de bloco.u em bins laterais de cfg.bin_lateral_m (H1).

    Pixels inválidos não entram na média; `cobertura` registra a fração válida do polígono do bloco.
    A coerência de um bin é a fração dos subtrechos (cfg.subtrecho_m) com vegetação >=
    cfg.limiar_presenca_subtrecho entre os subtrechos que têm pixel válido naquele bin.
    """
    if bloco.poligono is None:
        raise ErroContrato(f"bloco {bloco.id_bloco} sem polígono")
    nb = max(1, int(math.ceil((bloco.t_max_m - bloco.t_min_m) / cfg.bin_lateral_m)))
    t_m = bloco.t_min_m + (np.arange(nb) + 0.5) * cfg.bin_lateral_m
    vazio = PerfilLateral(bloco=bloco, t_m=t_m, vegetacao=np.full(nb, np.nan),
                          coerencia=np.full(nb, np.nan), cobertura=0.0)
    try:
        jan = fonte.ler_janela(tuple(bloco.poligono.bounds), cfg.resolucao_trabalho_m)
    except ErroContrato:
        return vazio
    h, w = jan.valores.shape
    dentro = ~geometry_mask([bloco.poligono], out_shape=(h, w), transform=jan.transform)
    n_dentro = int(dentro.sum())
    ok = jan.validade & dentro
    n_ok = int(ok.sum())
    if n_dentro == 0 or n_ok == 0:
        return vazio
    cobertura = n_ok / n_dentro
    ys, xs = np.nonzero(ok)
    px = jan.transform * (xs + 0.5, ys + 0.5)
    x, y = np.asarray(px[0]), np.asarray(px[1])
    ox, oy = bloco.origem
    s = (x - ox) * bloco.u[0] + (y - oy) * bloco.u[1] - bloco.s0_m
    t = (x - ox) * bloco.n[0] + (y - oy) * bloco.n[1]
    veg = jan.valores[ok].astype(np.float64)
    ib = np.clip(np.floor((t - bloco.t_min_m) / cfg.bin_lateral_m).astype(np.int64), 0, nb - 1)
    n_bin = np.bincount(ib, minlength=nb).astype(np.float64)
    v_bin = np.bincount(ib, weights=veg, minlength=nb)
    vegetacao = np.full(nb, np.nan)
    tem = n_bin > 0
    vegetacao[tem] = v_bin[tem] / n_bin[tem]
    ns = max(1, int(math.ceil(bloco.comprimento_m / cfg.subtrecho_m)))
    isub = np.clip(np.floor(s / cfg.subtrecho_m).astype(np.int64), 0, ns - 1)
    comb = isub * nb + ib
    n_c = np.bincount(comb, minlength=ns * nb).astype(np.float64).reshape(ns, nb)
    v_c = np.bincount(comb, weights=veg, minlength=ns * nb).reshape(ns, nb)
    valido_c = n_c > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        presente = (v_c / n_c) >= cfg.limiar_presenca_subtrecho
    presente &= valido_c
    n_val = valido_c.sum(axis=0)
    coerencia = np.full(nb, np.nan)
    coerencia[n_val > 0] = presente.sum(axis=0)[n_val > 0] / n_val[n_val > 0]
    return PerfilLateral(bloco=bloco, t_m=t_m, vegetacao=vegetacao, coerencia=coerencia,
                         cobertura=float(cobertura))
