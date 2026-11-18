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
from dataclasses import dataclass, replace

import numpy as np
from rasterio.features import geometry_mask
from scipy.signal import savgol_filter
from scipy.spatial import cKDTree
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


def estimar_direcao_regiao(fonte: FonteBinaria, regiao: Regiao, cfg: Config, *,
                           passo_grosso: float | None = None, passo_fino: float | None = None,
                           max_pontos: int | None = None) -> DirecaoFileiras:
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
    passo_grosso = cfg.passo_angulo_grosso_graus if passo_grosso is None else passo_grosso
    passo_fino = cfg.passo_angulo_fino_graus if passo_fino is None else passo_fino
    max_pontos = cfg.max_pontos_orientacao if max_pontos is None else max_pontos
    if n_ok > max_pontos:
        rng = np.random.default_rng(SEMENTE)
        sel = rng.choice(n_ok, max_pontos, replace=False)
        xs, ys, veg_all = xs[sel], ys[sel], veg_all[sel]
    ox, oy = jan.transform * (0.5, 0.5)
    px = abs(jan.transform.a)
    x = xs * px
    y = -ys * px  # norte para cima; origem local arbitrária
    del ox, oy
    frac_veg = float(veg_all.mean())
    if frac_veg < 0.02 or frac_veg > 0.98:
        raise ErroDeteccao(f"região {regiao.id_regiao}: vegetação {frac_veg:.1%}, sem contraste para orientar")

    grossos = np.arange(0.0, 180.0, passo_grosso)
    notas = np.array([_criterio(x, y, veg_all, a, cfg.bin_lateral_m, cfg) for a in grossos])
    melhor = float(grossos[int(np.argmax(notas))])
    finos = melhor + np.arange(-passo_grosso, passo_grosso + passo_fino / 2, passo_fino)
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


# ----------------------------------------------------------------------------- campo de direção (curvas)
@dataclass(frozen=True)
class CampoDirecao:
    """Direção das fileiras em janelas pequenas (modo_blocos="faixas"), já suavizada e alinhada a u_ref.

    `xy` são os centros das janelas; `angulos` os azimutes finais (graus, módulo 180). `vetor_em` interpola
    por ponderação inversa da distância sobre as janelas mais próximas (média do ângulo dobrado).
    """
    xy: np.ndarray
    angulos: np.ndarray
    u_ref: tuple[float, float]
    arvore: cKDTree

    def vetor_em(self, x: float, y: float, k: int = 4) -> tuple[float, float]:
        k = min(k, len(self.angulos))
        d, i = self.arvore.query([x, y], k=k)
        d, i = np.atleast_1d(d), np.atleast_1d(i)
        w = 1.0 / (d + 1.0) ** 2
        a2 = np.radians(2.0 * self.angulos[i])
        ang = math.degrees(math.atan2(float(np.sum(w * np.sin(a2))), float(np.sum(w * np.cos(a2))))) / 2.0
        return _alinhar(_vetor_provisorio(ang % 180.0), self.u_ref)

    def azimute_em(self, x: float, y: float) -> float:
        v = self.vetor_em(x, y)
        return math.degrees(math.atan2(v[0], v[1])) % 180.0


def _ajuste_local(i: int, xy: np.ndarray, ang: np.ndarray, peso: np.ndarray, validos: np.ndarray,
                  cfg: Config) -> float | None:
    """Ajuste plano (ângulo ~ a + b*dx + c*dy, ponderado, com uma rodada de rejeição de atípicos) nas
    janelas válidas a até cfg.raio_suavizacao_direcao_m de `i`. Devolve o ângulo ajustado em `i` (módulo 180)."""
    d = np.hypot(*(xy - xy[i]).T)
    viz = np.nonzero(validos & (d <= cfg.raio_suavizacao_direcao_m))[0]
    if len(viz) < 4:
        return None
    ref = ang[viz[0]]
    a = np.array([ref + _dif180(ang[j], ref) for j in viz])
    dx = xy[viz] - xy[i]
    A = np.column_stack([np.ones(len(viz)), dx])
    w = peso[viz].copy()
    for _ in range(2):
        if (w > 0).sum() < 4:
            return None
        coef, *_ = np.linalg.lstsq(A * np.sqrt(w)[:, None], a * np.sqrt(w), rcond=None)
        res = np.abs(a - A @ coef)
        w = np.where(res > cfg.desvio_campo_max_graus, 0.0, peso[viz])
    return float(coef[0]) % 180.0


def estimar_campo_direcao(fonte: FonteBinaria, area: AreaTalhao, cfg: Config
                          ) -> tuple[CampoDirecao, list[Regiao], tuple[float, float]]:
    """Campo de direção em janelas de cfg.janela_direcao_m sobre a área útil (modo_blocos="faixas").

    1) cada janela estima sua direção (mesma projeção por rotação, busca mais grossa);
    2) janela com direção não confiável, ou a mais de cfg.desvio_campo_max_graus do ajuste plano das
       vizinhas, recebe o valor do ajuste (herdada=True, marcada), nunca silenciosa;
    3) u_ref é a mediana circular das direções; sentidos alinhados a u_ref.
    Devolve (campo, janelas como Regiao com direção, u_ref). Raises: ErroDeteccao se nada for estimável.
    """
    x0, y0, x1, y1 = area.bounds
    lado = cfg.janela_direcao_m
    janelas: list[Regiao] = []
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            rec = area.poligono_util.intersection(box(x, y, min(x + lado, x1), min(y + lado, y1)))
            if (not rec.is_empty and rec.geom_type in ("Polygon", "MultiPolygon")
                    and rec.area >= 0.3 * lado * lado):
                janelas.append(Regiao(id_regiao=f"{area.talhao.id}-J{len(janelas) + 1:04d}",
                                      talhao=area.talhao.id, poligono=rec, direcao=None))
            y += lado
        x += lado
    if not janelas:
        raise ErroDeteccao("nenhuma janela de direção na área útil")
    n = len(janelas)
    xy = np.array([j.poligono.centroid.coords[0] for j in janelas])
    ang = np.zeros(n)
    conf = np.zeros(n)
    ok = np.zeros(n, dtype=bool)
    for i, j in enumerate(janelas):
        try:
            d = estimar_direcao_regiao(fonte, j, cfg, passo_grosso=cfg.passo_angulo_grosso_campo_graus,
                                       passo_fino=cfg.passo_angulo_fino_campo_graus,
                                       max_pontos=cfg.max_pontos_janela_direcao)
        except ErroDeteccao:
            continue
        if d.confianca >= cfg.confianca_min_direcao:
            ang[i], conf[i], ok[i] = d.azimute_graus, d.confianca, True
    if not ok.any():
        raise ErroDeteccao("nenhuma janela com direção das fileiras estimável")
    area_j = np.array([j.poligono.area for j in janelas])
    peso = np.where(ok, conf * area_j, 0.0)
    final = np.where(ok, ang, np.nan)
    herdada = ~ok
    for i in range(n):
        aj = _ajuste_local(i, xy, ang, peso, ok, cfg)
        if aj is None:
            continue
        if not ok[i] or abs(_dif180(ang[i], aj)) > cfg.desvio_campo_max_graus:
            final[i], herdada[i] = aj, True
    usar = ~np.isnan(final)
    # janelas sem estimativa nem ajuste possível: herdam o azimute da janela válida mais próxima
    if (~usar).any():
        arv = cKDTree(xy[usar])
        _, near = arv.query(xy[~usar])
        final[~usar] = final[usar][near]
    u_ref = _vetor_provisorio(_mediana_circular(list(final), list(np.maximum(peso, 1e-6))))
    campo = CampoDirecao(xy=xy, angulos=final, u_ref=u_ref, arvore=cKDTree(xy))
    saida = [replace(j, direcao=DirecaoFileiras(
        azimute_graus=float(final[i]), vetor=_alinhar(_vetor_provisorio(float(final[i])), u_ref),
        confianca=0.0 if herdada[i] else float(conf[i]), herdada=bool(herdada[i])))
        for i, j in enumerate(janelas)]
    return campo, saida, u_ref
