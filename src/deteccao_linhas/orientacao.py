"""Orientação das fileiras por região (docs/interfaces-deteccao.md, seção 6.3).

Base: Ferreira et al. (2025), projeção por rotação com suavização Savitzky-Golay (a ideia geral).
CRITÉRIO DE ESCOLHA DO ÂNGULO (decisão de implementação, HIPÓTESE, a conferir contra o método do
artigo): para cada ângulo candidato projeta-se a vegetação sobre o eixo perpendicular à direção
candidata, em bins de cfg.bin_lateral_m; o perfil é a fração de vegetação por bin (só bins com
pixels válidos), suavizado por Savitzky-Golay; o ângulo escolhido maximiza a variância ponderada
(pelo número de pixels válidos do bin) desse perfil. Busca em dois passos (grosso e fino).
Confiança = (melhor - mediana dos candidatos grossos) / melhor, em [0, 1].
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from rasterio.features import geometry_mask
from scipy.signal import savgol_filter
from shapely.geometry import box

from .config import Config
from .indice_binarizacao import FonteBinaria
from .tipos import AreaTalhao, DirecaoFileiras, ErroContrato, ErroDeteccao, Regiao

MIN_PIXELS_VALIDOS = 10000
SEMENTE = 12345


def dividir_em_regioes(area: AreaTalhao, cfg: Config) -> list[Regiao]:
    """Grade de lado cfg.regiao_m sobre a área útil, recortada pelo polígono útil.

    Regiões com área menor que cfg.area_minima_regiao_m2 herdam direção (decidido em estimar_direcoes).
    Raises: ErroContrato se não restar região.
    """
    x0, y0, x1, y1 = area.bounds
    regioes: list[Regiao] = []
    n = 0
    ix = 0
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            recorte = area.poligono_util.intersection(box(x, y, min(x + cfg.regiao_m, x1), min(y + cfg.regiao_m, y1)))
            if not recorte.is_empty and recorte.area > 0 and recorte.geom_type in ("Polygon", "MultiPolygon"):
                n += 1
                regioes.append(Regiao(id_regiao=f"{area.talhao.id}-R{n:03d}", talhao=area.talhao.id,
                                      poligono=recorte, direcao=None))
            y += cfg.regiao_m
        x += cfg.regiao_m
        ix += 1
    if not regioes:
        raise ErroContrato(f"talhão {area.talhao.id!r}: nenhuma região na área útil")
    return regioes


def _vetor_provisorio(azimute: float) -> tuple[float, float]:
    a = math.radians(azimute)
    ux, uy = math.sin(a), math.cos(a)
    if uy < -1e-12 or (abs(uy) <= 1e-12 and ux < 0):
        ux, uy = -ux, -uy
    return (ux, uy)


def _criterio(x: np.ndarray, y: np.ndarray, veg: np.ndarray, angulo: float, bin_m: float, cfg: Config) -> float:
    a = math.radians(angulo)
    t = x * math.cos(a) - y * math.sin(a)
    idx = np.floor((t - t.min()) / bin_m).astype(np.int64)
    n = int(idx.max()) + 1
    validos = np.bincount(idx, minlength=n).astype(np.float64)
    soma = np.bincount(idx, weights=veg, minlength=n)
    ok = validos > 0.05 * validos.max()
    if ok.sum() < cfg.sg_janela + 2:
        return 0.0
    frac = np.zeros(n)
    frac[ok] = soma[ok] / validos[ok]
    # preenche bins sem dado com a média para o filtro não criar falsos contrastes
    frac[~ok] = np.average(frac[ok], weights=validos[ok])
    suave = savgol_filter(frac, cfg.sg_janela, cfg.sg_ordem)
    w = validos * ok
    media = np.average(suave, weights=w)
    return float(np.average((suave - media) ** 2, weights=w))


def estimar_direcao_regiao(fonte: FonteBinaria, regiao: Regiao, cfg: Config) -> DirecaoFileiras:
    """Projeção por rotação na janela da região, em dois passos. Vetor com sentido provisório (norte positivo).

    Raises: ErroDeteccao se a região não tiver pixels válidos suficientes.
    """
    try:
        jan = fonte.ler_janela(tuple(regiao.poligono.bounds), cfg.resolucao_trabalho_m)
    except ErroContrato as exc:
        raise ErroDeteccao(f"região {regiao.id_regiao}: fora do ortomosaico") from exc
    h, w = jan.valores.shape
    dentro = ~geometry_mask([regiao.poligono], out_shape=(h, w), transform=jan.transform)
    ok = jan.validade & dentro
    n_ok = int(ok.sum())
    if n_ok < MIN_PIXELS_VALIDOS:
        raise ErroDeteccao(f"região {regiao.id_regiao}: só {n_ok} pixels válidos")
    ys, xs = np.nonzero(ok)
    veg_all = jan.valores[ok].astype(np.float64)
    if n_ok > cfg.max_pontos_orientacao:
        rng = np.random.default_rng(SEMENTE)
        sel = rng.choice(n_ok, cfg.max_pontos_orientacao, replace=False)
        xs, ys, veg_all = xs[sel], ys[sel], veg_all[sel]
    ox, oy = jan.transform * (0.5, 0.5)
    px = abs(jan.transform.a)
    x = xs * px
    y = -ys * px  # norte para cima; origem local arbitrária
    del ox, oy
    frac_veg = float(veg_all.mean())
    if frac_veg < 0.02 or frac_veg > 0.98:
        raise ErroDeteccao(f"região {regiao.id_regiao}: vegetação {frac_veg:.1%}, sem contraste para orientar")

    grossos = np.arange(0.0, 180.0, cfg.passo_angulo_grosso_graus)
    notas = np.array([_criterio(x, y, veg_all, a, cfg.bin_lateral_m, cfg) for a in grossos])
    melhor = float(grossos[int(np.argmax(notas))])
    finos = melhor + np.arange(-cfg.passo_angulo_grosso_graus,
                               cfg.passo_angulo_grosso_graus + cfg.passo_angulo_fino_graus / 2,
                               cfg.passo_angulo_fino_graus)
    notas_f = np.array([_criterio(x, y, veg_all, a, cfg.bin_lateral_m, cfg) for a in finos])
    k = int(np.argmax(notas_f))
    azimute = float(finos[k]) % 180.0
    topo = float(notas_f[k])
    conf = 0.0 if topo <= 0 else float(np.clip((topo - np.median(notas)) / topo, 0.0, 1.0))
    return DirecaoFileiras(azimute_graus=azimute, vetor=_vetor_provisorio(azimute), confianca=conf, herdada=False)


def _dif180(a: float, b: float) -> float:
    """a - b em [-90, 90)."""
    return (a - b + 90.0) % 180.0 - 90.0


def _mediana_circular(angulos: list[float], pesos: list[float]) -> float:
    """Mediana ponderada módulo 180: média circular (ângulo dobrado) como centro, depois mediana
    ponderada dos desvios assinados."""
    ang = np.array(angulos)
    p = np.array(pesos, dtype=float)
    if p.sum() <= 0:
        p = np.ones_like(p)
    c = np.sum(p * np.cos(np.radians(2 * ang)))
    s = np.sum(p * np.sin(np.radians(2 * ang)))
    centro = (math.degrees(math.atan2(s, c)) / 2.0) % 180.0
    dev = np.array([_dif180(a, centro) for a in ang])
    ordem = np.argsort(dev)
    acum = np.cumsum(p[ordem])
    k = int(np.searchsorted(acum, acum[-1] / 2.0))
    return (centro + float(dev[ordem][k])) % 180.0


def _alinhar(vetor: tuple[float, float], u_ref: tuple[float, float]) -> tuple[float, float]:
    return vetor if vetor[0] * u_ref[0] + vetor[1] * u_ref[1] >= 0 else (-vetor[0], -vetor[1])


def estimar_direcoes(fonte: FonteBinaria, regioes: list[Regiao], cfg: Config
                     ) -> tuple[list[Regiao], tuple[float, float]]:
    """Estima a direção de cada região, define u_ref e alinha o sentido a u_ref.

    Região sem estimativa confiável, ou a mais de cfg.desvio_angular_max_graus da mediana das
    vizinhas, herda a direção das vizinhas (herdada=True, nunca silenciosa).
    Raises: ErroDeteccao se nenhuma região tiver direção estimável.
    """
    est: dict[str, DirecaoFileiras | None] = {}
    for r in regioes:
        if r.poligono.area < cfg.area_minima_regiao_m2:
            est[r.id_regiao] = None
            continue
        try:
            d = estimar_direcao_regiao(fonte, r, cfg)
        except ErroDeteccao:
            est[r.id_regiao] = None
            continue
        est[r.id_regiao] = d if d.confianca >= cfg.confianca_min_direcao else None
    confiaveis = [r for r in regioes if est[r.id_regiao] is not None]
    if not confiaveis:
        raise ErroDeteccao("nenhuma região com direção das fileiras estimável")
    ang_g = _mediana_circular([est[r.id_regiao].azimute_graus for r in confiaveis],
                              [r.poligono.area * est[r.id_regiao].confianca for r in confiaveis])
    u_ref = _vetor_provisorio(ang_g)

    def vizinhas(r: Regiao, entre: list[Regiao]) -> list[Regiao]:
        g = r.poligono.buffer(1.0)
        return [o for o in entre if o.id_regiao != r.id_regiao and g.intersects(o.poligono)]

    # 1) regiões confiáveis que destoam das vizinhas confiáveis passam a herdar
    herdar: set[str] = set()
    for r in confiaveis:
        viz = vizinhas(r, confiaveis)
        ref = (_mediana_circular([est[o.id_regiao].azimute_graus for o in viz],
                                 [o.poligono.area * est[o.id_regiao].confianca for o in viz])
               if viz else ang_g)
        meu = est[r.id_regiao].azimute_graus
        destoa = abs(_dif180(meu, ref)) > cfg.desvio_angular_max_graus
        # vizinhas que discordam entre si não dão referência confiável: exige também desvio da global
        angs_viz = [est[o.id_regiao].azimute_graus for o in viz]
        discordam = any(abs(_dif180(a, b)) > cfg.desvio_angular_max_graus for a in angs_viz for b in angs_viz)
        if destoa and (not discordam or abs(_dif180(meu, ang_g)) > cfg.desvio_angular_max_graus):
            herdar.add(r.id_regiao)
    firmes = [r for r in confiaveis if r.id_regiao not in herdar]
    if not firmes:  # tudo destoou: mantém as confiáveis como estão (marcação não é uma opção)
        firmes, herdar = confiaveis, set()
    # 2) herdeiras: mediana das vizinhas firmes; sem vizinha firme, a global
    angulo_final: dict[str, float] = {r.id_regiao: est[r.id_regiao].azimute_graus for r in firmes}
    herdadas = [r for r in regioes if r.id_regiao not in angulo_final]
    for _ in range(len(herdadas) + 1):  # propaga a partir de quem já tem ângulo
        pendentes = []
        for r in herdadas:
            if r.id_regiao in angulo_final:
                continue
            com_ang = [o for o in regioes if o.id_regiao in angulo_final]
            viz = vizinhas(r, com_ang)
            if viz:
                angulo_final[r.id_regiao] = _mediana_circular(
                    [angulo_final[o.id_regiao] for o in viz], [o.poligono.area for o in viz])
            else:
                pendentes.append(r)
        if not pendentes:
            break
        if len(pendentes) == len([r for r in herdadas if r.id_regiao not in angulo_final]):
            for r in pendentes:
                angulo_final[r.id_regiao] = ang_g
            break
    saida: list[Regiao] = []
    for r in regioes:
        herdada = r.id_regiao not in {f.id_regiao for f in firmes}
        ang = angulo_final[r.id_regiao]
        conf = 0.0 if herdada else est[r.id_regiao].confianca
        vetor = _alinhar(_vetor_provisorio(ang), u_ref)
        saida.append(replace(r, direcao=DirecaoFileiras(azimute_graus=ang, vetor=vetor,
                                                        confianca=conf, herdada=herdada)))
    return saida, u_ref
