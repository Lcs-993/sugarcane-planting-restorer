"""Pente de periodicidade 1,50 m sobre o perfil lateral (docs/interfaces-deteccao.md, seção 6.5).

H2 (hipótese): um pente com fase local e tolerância localiza as fileiras e absorve o salto entre
passadas. Tudo aqui é decisão de implementação sem fonte lida:
- picos do perfil suavizado (gaussiana, cfg.sigma_suavizacao_perfil_m); centro = ponto médio da largura
  a meia proeminência; largura = essa largura; picos que tocam a borda lateral do bloco são ignorados
  (fileira cortada); picos mais próximos que cfg.distancia_fusao_picos_m são fundidos (fica o mais proeminente);
- janelas de fase: largura cfg.dentes_por_janela_fase * espaçamento, passo de um dente, a partir de t_min;
  a fase de cada janela maximiza a soma, sobre os picos da janela, de proeminência * max(0, 1 - d/semijanela),
  com d a distância do pico ao dente do pente; refinada pela média ponderada dos desvios;
- um pico vira posição se, para alguma janela que o contenha, d <= cfg.semijanela_dente_m; ajuste_pente = 1 - d/semijanela;
  pico fora do pente (erva, por exemplo) não gera posição e não é preenchido.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import shapely
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, peak_widths

from .config import Config
from .tipos import PerfilLateral, PosicaoFileira, ResultadoPente

PAD_BINS = 15
PASSO_GRADE_FASE_M = 0.01


def _picos(perfil: PerfilLateral, cfg: Config) -> list[dict]:
    """Picos do perfil: lista de dicts com t, largura, proeminencia, coerencia (ordenados por t)."""
    v = np.nan_to_num(perfil.vegetacao, nan=0.0)
    if v.size < 5 or perfil.cobertura < cfg.cobertura_min_bloco or v.max() <= 0:
        return []
    bin_m = cfg.bin_lateral_m
    suave = gaussian_filter1d(v, max(cfg.sigma_suavizacao_perfil_m / bin_m, 1e-6), mode="nearest")
    pad = np.concatenate([np.zeros(PAD_BINS), suave, np.zeros(PAD_BINS)])
    dist = max(1, int(round(cfg.distancia_min_picos_m / bin_m)))
    idx, props = find_peaks(pad, prominence=cfg.proeminencia_min, distance=dist)
    if idx.size == 0:
        return []
    _, _, esq, dir_ = peak_widths(pad, idx, rel_height=0.5, prominence_data=(props["prominences"],
                                                                         props["left_bases"], props["right_bases"]))
    picos: list[dict] = []
    n = v.size
    for k, i in enumerate(idx):
        e, d = esq[k] - PAD_BINS, dir_[k] - PAD_BINS
        if e <= 0.5 or d >= n - 1.5:  # toca a borda lateral: fileira cortada pelo bloco
            continue
        centro_bin = (e + d) / 2.0
        t = float(perfil.t_m[0] + centro_bin * bin_m)
        lo, hi = max(0, int(math.floor(e))), min(n, int(math.ceil(d)) + 1)
        coer = np.nanmean(perfil.coerencia[lo:hi]) if np.isfinite(perfil.coerencia[lo:hi]).any() else 0.0
        picos.append({"t": t, "largura": float((d - e) * bin_m), "prom": float(props["prominences"][k]),
                      "coer": float(coer)})
    picos.sort(key=lambda p: p["t"])
    mudou = True
    while mudou and len(picos) > 1:
        mudou = False
        for a, b in zip(picos, picos[1:]):
            if b["t"] - a["t"] < cfg.distancia_fusao_picos_m:
                picos.remove(a if a["prom"] < b["prom"] else b)
                mudou = True
                break
    return picos


def _janelas(perfil: PerfilLateral, cfg: Config) -> list[tuple[float, float]]:
    p = cfg.espacamento_fileiras_ref_m
    t0, t1 = float(perfil.t_m[0]), float(perfil.t_m[-1])
    larg = cfg.dentes_por_janela_fase * p
    if t1 - t0 <= larg:
        return [(t0 - 1e-9, t1 + 1e-9)]
    n = int(math.floor((t1 - t0 - larg) / p)) + 1
    jan = [(t0 + k * p, t0 + k * p + larg) for k in range(n)]
    if jan[-1][1] < t1:  # cauda não coberta
        jan.append((t1 - larg, t1 + 1e-9))
    return jan


def _dist_dente(t: float, fase: float, p: float) -> float:
    return abs(((t - fase + p / 2.0) % p) - p / 2.0)


def _fase_janela(picos: list[dict], cfg: Config) -> float | None:
    p, tol = cfg.espacamento_fileiras_ref_m, cfg.semijanela_dente_m
    if not picos:
        return None
    ts = np.array([q["t"] for q in picos])
    ws = np.array([q["prom"] for q in picos])
    grade = np.arange(0.0, p, PASSO_GRADE_FASE_M)
    d = np.abs(((ts[None, :] - grade[:, None] + p / 2.0) % p) - p / 2.0)
    nota = (ws[None, :] * np.clip(1.0 - d / tol, 0.0, None)).sum(axis=1)
    fase = float(grade[int(np.argmax(nota))])
    desv = ((ts - fase + p / 2.0) % p) - p / 2.0
    perto = np.abs(desv) <= tol
    if perto.any():
        fase += float(np.average(desv[perto], weights=ws[perto]))
    return fase % p


def ajustar_fase(perfil: PerfilLateral, cfg: Config) -> list[float]:
    """Fase local do pente em janelas deslizantes (uma por dente). Janela sem pico herda a fase
    da janela mais próxima com pico (só define onde procurar dentes; nenhuma posição é inventada).
    Perfil sem pico acima de cfg.proeminencia_min devolve lista vazia."""
    picos = _picos(perfil, cfg)
    if not picos:
        return []
    fases: list[float | None] = []
    for lo, hi in _janelas(perfil, cfg):
        fases.append(_fase_janela([q for q in picos if lo <= q["t"] < hi], cfg))
    com = [i for i, f in enumerate(fases) if f is not None]
    return [fases[i] if fases[i] is not None else fases[min(com, key=lambda j: abs(j - i))]
            for i in range(len(fases))]


def localizar_dentes(perfil: PerfilLateral, fases: list[float], cfg: Config) -> tuple[PosicaoFileira, ...]:
    """Em cada dente do pente, a posição do pico dentro de cfg.semijanela_dente_m. Dente sem pico: sem
    posição (nunca preenche). salto=True onde o espaçamento à vizinha foge do de referência por mais de
    cfg.tolerancia_espacamento_m. confianca ainda 0: preenchida por ajustar_bloco."""
    if not fases:
        return ()
    p, tol = cfg.espacamento_fileiras_ref_m, cfg.semijanela_dente_m
    janelas = _janelas(perfil, cfg)
    bloco = perfil.bloco
    s_mid = bloco.s0_m + bloco.comprimento_m / 2.0
    aceitos: list[tuple[dict, float]] = []
    for q in _picos(perfil, cfg):
        cands = [fases[k] for k, (lo, hi) in enumerate(janelas) if lo <= q["t"] < hi]
        if not cands:
            cands = [fases[min(range(len(janelas)), key=lambda k: abs((janelas[k][0] + janelas[k][1]) / 2 - q["t"]))]]
        d = min(_dist_dente(q["t"], f, p) for f in cands)
        if d <= tol:
            aceitos.append((q, d))
    posicoes: list[PosicaoFileira] = []
    for i, (q, d) in enumerate(aceitos):
        esp = aceitos[i + 1][0]["t"] - q["t"] if i + 1 < len(aceitos) else None
        salto = esp is not None and abs(esp - p) > cfg.tolerancia_espacamento_m
        x = bloco.origem[0] + s_mid * bloco.u[0] + q["t"] * bloco.n[0]
        y = bloco.origem[1] + s_mid * bloco.u[1] + q["t"] * bloco.n[1]
        posicoes.append(PosicaoFileira(
            id_bloco=bloco.id_bloco, t_m=q["t"], x=float(x), y=float(y), largura_m=q["largura"],
            proeminencia=q["prom"], coerencia=q["coer"], ajuste_pente=float(max(0.0, 1.0 - d / tol)),
            espacamento_vizinha_m=None if esp is None else float(esp), salto=bool(salto), confianca=0.0))
    return tuple(posicoes)


def ajustar_bloco(perfil: PerfilLateral, cfg: Config) -> ResultadoPente:
    """Encadeia ajustar_fase e localizar_dentes; calcula a confiança de cada posição (qualidade)."""
    from .qualidade import calcular_confianca

    fases = ajustar_fase(perfil, cfg)
    pos = tuple(replace(q, confianca=calcular_confianca(q, cfg)) for q in localizar_dentes(perfil, fases, cfg))
    if perfil.bloco.nucleo is not None:  # modo "faixas": a folga lateral só serve para enxergar a fileira inteira
        nucleo = perfil.bloco.nucleo.buffer(0.02)
        pos = tuple(q for q in pos if nucleo.contains(shapely.Point(q.x, q.y)))
    fase_global = float(np.median(fases)) if fases else None
    return ResultadoPente(bloco=perfil.bloco, posicoes=pos, fase_m=fase_global)
