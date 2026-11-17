"""Módulo qualidade (regras geométricas básicas de docs/arquitetura.md; docs/interfaces-fase1.md, 6.6).

Fora desta fase: espaçamento entre fileiras de passadas vizinhas (sobreposição e vão).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .config import Config
from .tipos import EstacaoDesvio

# HIPÓTESE (sem fonte lida): estação 'estimada' (uma só fileira) vale metade da confiança da detecção.
FATOR_ESTIMADO = 0.5
# HIPÓTESE (sem fonte lida): teto de confiança de uma estação 'duvidosa'.
TETO_CONFIANCA_DUVIDOSA = 0.3
# HIPÓTESE (sem fonte lida): penalidade máxima por estar na borda da tolerância (fator 1 - PENALIDADE).
PENALIDADE_TOLERANCIA = 0.5

_BOAS = ("detectado", "estimado")


def _largura_fora(w: float, cfg: Config) -> float:
    """Distância (m) da largura ao intervalo [mín, máx] da faixa; 0 se dentro."""
    return max(0.0, cfg.largura_faixa_min_m - w, w - cfg.largura_faixa_max_m)


def avaliar_geometria(est: EstacaoDesvio, cfg: Config) -> EstacaoDesvio:
    """Marca 'duvidoso' se |espacamento_gemeas_m - 1,50| > tolerancia_espacamento_gemeas_m,
    ou se a largura de alguma faixa estiver fora de [0,45 - tol, 0,50 + tol]."""
    if est.status not in _BOAS:
        return est
    if est.espacamento_gemeas_m is not None:
        if abs(est.espacamento_gemeas_m - cfg.espacamento_gemeas_ref_m) > cfg.tolerancia_espacamento_gemeas_m:
            return replace(est, status="duvidoso")
    for w in (est.largura_esq_m, est.largura_dir_m):
        if w is not None and _largura_fora(w, cfg) > cfg.tolerancia_largura_m:
            return replace(est, status="duvidoso")
    return est


def marcar_saltos(estacoes: list[EstacaoDesvio], cfg: Config) -> list[EstacaoDesvio]:
    """Marca 'duvidoso' a estação cujo desvio difere da mediana local dos vizinhos por mais de
    limite_variacao_m (ruído de detecção; o trator não muda de trajetória bruscamente).

    Vizinhos: estações boas (detectado ou estimado, ainda não reprovadas) em até
    janela_mediana // 2 + 1 posições de cada lado, excluída a própria (HIPÓTESE de implementação).
    Estação sem vizinho bom não é julgada. Todas são comparadas contra o estado de entrada, de modo
    que um salto isolado não contamina os vizinhos.
    """
    alcance = cfg.janela_mediana // 2 + 1
    boas = [e.status in _BOAS and e.desvio_m is not None for e in estacoes]
    saida = list(estacoes)
    for i, e in enumerate(estacoes):
        if not boas[i]:
            continue
        viz = [
            estacoes[j].desvio_m
            for j in range(max(0, i - alcance), min(len(estacoes), i + alcance + 1))
            if j != i and boas[j]
        ]
        if not viz:
            continue
        if abs(e.desvio_m - float(np.median(viz))) > cfg.limite_variacao_m:
            saida[i] = replace(e, status="duvidoso")
    return saida


def calcular_confianca(est: EstacaoDesvio, cfg: Config) -> float:
    """Confiança de 0 a 1 combinando a confiança de detecção das fileiras, o status e a
    proximidade das tolerâncias. A fórmula é HIPÓTESE (sem fonte lida):

    confianca = confianca_detecção x f_espaçamento x f_largura x (FATOR_ESTIMADO se estimada),
    onde cada f cai de 1 (no valor de referência) a 1 - PENALIDADE_TOLERANCIA (na borda da
    tolerância). Estação duvidosa fica limitada a TETO_CONFIANCA_DUVIDOSA; sem desvio, 0.
    """
    if est.desvio_m is None:
        return 0.0
    base = float(np.clip(est.confianca, 0.0, 1.0))
    f_esp = 1.0
    if est.espacamento_gemeas_m is not None:
        dev = abs(est.espacamento_gemeas_m - cfg.espacamento_gemeas_ref_m)
        f_esp = 1.0 - PENALIDADE_TOLERANCIA * min(1.0, dev / cfg.tolerancia_espacamento_gemeas_m)
    f_larg = 1.0
    for w in (est.largura_esq_m, est.largura_dir_m):
        if w is not None:
            f_larg = min(f_larg, 1.0 - PENALIDADE_TOLERANCIA * min(1.0, _largura_fora(w, cfg) / cfg.tolerancia_largura_m))
    c = base * f_esp * f_larg
    if est.status == "estimado":
        c *= FATOR_ESTIMADO
    if est.status == "duvidoso":
        c = min(c, TETO_CONFIANCA_DUVIDOSA)
    return float(np.clip(c, 0.0, 1.0))


def avaliar_passada(estacoes: list[EstacaoDesvio], cfg: Config) -> list[EstacaoDesvio]:
    """Encadeia as três funções acima e devolve as estações com status e confiança finais de detecção."""
    ev = [avaliar_geometria(e, cfg) for e in estacoes]
    ev = marcar_saltos(ev, cfg)
    return [replace(e, confianca=calcular_confianca(e, cfg)) for e in ev]
