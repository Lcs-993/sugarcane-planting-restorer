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


def _retangulo(cx: float, cy: float, u: tuple[float, float], comp: float, larg: float) -> Polygon:
    ux, uy = u
    nx, ny = -uy, ux
    a, b = comp / 2.0, larg / 2.0
    return Polygon([(cx + s * ux + t * nx, cy + s * uy + t * ny) for s, t in ((-a, -b), (a, -b), (a, b), (-a, b))])


def _linha_de_corrente(campo, semente: tuple[float, float], passo: float, limite: Polygon, max_passos: int
                       ) -> list[tuple[float, float]]:
    """Centros dos blocos ao longo da linha de corrente do campo por `semente`, nos dois sentidos, enquanto
    ficarem dentro de `limite` (RK2, passo = distância entre centros)."""
    def marchar(sentido: float) -> list[tuple[float, float]]:
        x, y = semente
        saida: list[tuple[float, float]] = []
        for _ in range(max_passos):
            vx, vy = campo.vetor_em(x, y)
            mx, my = x + sentido * passo / 2 * vx, y + sentido * passo / 2 * vy
            vx, vy = campo.vetor_em(mx, my)
            x, y = x + sentido * passo * vx, y + sentido * passo * vy
            if not limite.contains(shapely.Point(x, y)):
                break
            saida.append((x, y))
        return saida
    return marchar(-1.0)[::-1] + [semente] + marchar(1.0)


def gerar_blocos_faixas(campo, area_util, u_ref: tuple[float, float], c_ref: tuple[float, float],
                        cfg: Config) -> list[Bloco]:
    """Blocos ao longo de linhas de corrente do campo de direção (modo_blocos="faixas").

    Cada faixa tem largura cfg.largura_corredor_m; os blocos de uma faixa são retângulos de
    cfg.comprimento_bloco_m orientados pela direção local do campo, espaçados de passo_blocos.
    A região ainda não coberta (`restante`) escolhe a próxima semente (vértice mais recuado em u_ref);
    o núcleo do bloco é o retângulo da faixa recortado por `restante` no início da faixa, de modo que
    faixas vizinhas não contam a mesma fileira duas vezes. O perfil é lido numa área maior (folga lateral
    cfg.margem_lateral_bloco_m) e só posições no núcleo são aceitas (ver pente.ajustar_bloco).
    HIPÓTESE (sem fonte lida): tudo isto é decisão de implementação.
    """
    L, W, M = cfg.comprimento_bloco_m, cfg.largura_corredor_m, cfg.margem_lateral_bloco_m
    passo_blocos = min(cfg.passo_bloco_faixas_m, L)
    area_min = max(30.0, cfg.lateral_minima_bloco_m * COMPRIMENTO_MIN_BLOCO_M)
    restante = area_util
    blocos: list[Bloco] = []
    nf = 0
    for _ in range(5000):
        partes = [g for g in getattr(restante, "geoms", [restante]) if g.geom_type == "Polygon" and g.area >= area_min]
        if not partes:
            break
        # vértice mais recuado em u_ref entre todas as partes restantes
        melhor = None
        for g in partes:
            pts = _coords(g.exterior)
            sv = (pts[:, 0] - c_ref[0]) * u_ref[0] + (pts[:, 1] - c_ref[1]) * u_ref[1]
            i = int(np.argmin(sv))
            if melhor is None or sv[i] < melhor[0]:
                melhor = (float(sv[i]), g, pts[i])
        _, g, v = melhor
        ce = g.centroid
        dv = np.array([ce.x - v[0], ce.y - v[1]])
        nv = float(np.hypot(*dv))
        sem = (float(v[0]), float(v[1]))
        if nv > 1e-6:
            cand = (v[0] + dv[0] / nv * min(W / 2.0, nv), v[1] + dv[1] / nv * min(W / 2.0, nv))
            if g.contains(shapely.Point(*cand)):
                sem = (float(cand[0]), float(cand[1]))
        limite = area_util.buffer(L)
        max_passos = int(2.0 * (area_util.bounds[2] - area_util.bounds[0] + area_util.bounds[3] - area_util.bounds[1])
                         / passo_blocos) + 10
        centros = _linha_de_corrente(campo, sem, passo_blocos, limite, max_passos)
        nf += 1
        n = 0
        faixa = []
        for (cx, cy) in centros:
            u = campo.vetor_em(cx, cy)
            nx, ny = -u[1], u[0]
            ret_ext = _retangulo(cx, cy, u, L, W + 2 * M)
            ret_nuc = _retangulo(cx, cy, u, L, W)
            faixa.append(ret_nuc)
            poli = ret_ext.intersection(area_util)
            nucleo = ret_nuc.intersection(restante)
            if poli.is_empty or nucleo.is_empty or nucleo.area < 1.0:
                continue
            poli = _so_poligonos(poli)
            if poli is None:
                continue
            p = _coords(poli)
            sp = (p[:, 0] - cx) * u[0] + (p[:, 1] - cy) * u[1]
            tp = (p[:, 0] - cx) * nx + (p[:, 1] - cy) * ny
            bs0, bs1, bt0, bt1 = sp.min(), sp.max(), tp.min(), tp.max()
            if bs1 - bs0 < COMPRIMENTO_MIN_BLOCO_M or bt1 - bt0 < cfg.lateral_minima_bloco_m:
                continue
            n += 1
            tc = (bt0 + bt1) / 2.0
            centro = (cx + (bs0 + bs1) / 2.0 * u[0] + tc * nx, cy + (bs0 + bs1) / 2.0 * u[1] + tc * ny)
            s_glob = (centro[0] - c_ref[0]) * u_ref[0] + (centro[1] - c_ref[1]) * u_ref[1]
            blocos.append(Bloco(
                id_bloco=f"F{nf:03d}-B{n:03d}", id_regiao=f"F{nf:03d}", origem=(cx, cy), u=(float(u[0]), float(u[1])),
                n=(nx, ny), s0_m=float(bs0), comprimento_m=float(bs1 - bs0), t_min_m=float(bt0), t_max_m=float(bt1),
                s_global_m=float(s_glob), poligono=poli, nucleo=_so_poligonos(nucleo), curvatura_1_m=0.0))
        cobertura = shapely.union_all(faixa) if faixa else None
        if cobertura is None or cobertura.is_empty:  # garante progresso
            cobertura = shapely.Point(*sem).buffer(W / 2.0)
        restante = restante.difference(cobertura)
        if restante.is_empty:
            break
    blocos.sort(key=lambda b: (b.s_global_m, b.id_bloco))
    return blocos


def _so_poligonos(geom):
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom if geom.area > 0 else None
    partes = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(partes) if partes else None


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
