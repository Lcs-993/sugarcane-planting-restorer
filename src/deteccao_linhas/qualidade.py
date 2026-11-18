"""Confiança e avaliação das trilhas (docs/interfaces-deteccao.md, seção 6.7)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from shapely.geometry import LineString

from .config import Config
from .tipos import ErroContrato, FileiraAvaliada, PosicaoFileira, Status, Trilha


def calcular_confianca(pos: PosicaoFileira, cfg: Config) -> float:
    """Combina contraste, coerência longitudinal, largura e ajuste ao pente (HIPÓTESE H5).

    Fórmula (hipótese, sem fonte lida), cada componente em [0, 1]:
      contraste  = clip((proeminência - proeminencia_min) / (proeminencia_saturacao - proeminencia_min), 0, 1)
      coerência  = coerência longitudinal do pico (fração de subtrechos com vegetação)
      largura    = 1 dentro de [largura_faixa_min_m, largura_faixa_max_m]; cai linearmente a 0 a
                   tolerancia_largura_m fora da faixa; 0 se a largura não foi medida
      ajuste     = ajuste ao pente
    confiança = soma ponderada com cfg.pesos_confianca (contraste, coerência, largura, ajuste).
    """
    contraste = (pos.proeminencia - cfg.proeminencia_min) / (cfg.proeminencia_saturacao - cfg.proeminencia_min)
    contraste = min(1.0, max(0.0, contraste))
    coerencia = min(1.0, max(0.0, pos.coerencia))
    if pos.largura_m is None:
        largura = 0.0
    else:
        fora = max(cfg.largura_faixa_min_m - pos.largura_m, pos.largura_m - cfg.largura_faixa_max_m, 0.0)
        largura = max(0.0, 1.0 - fora / cfg.tolerancia_largura_m)
    ajuste = min(1.0, max(0.0, pos.ajuste_pente))
    w = cfg.pesos_confianca
    return float(w[0] * contraste + w[1] * coerencia + w[2] * largura + w[3] * ajuste)


def classificar_ponto(confianca: float, cfg: Config) -> Status:
    """'duvidoso' se confianca < cfg.limiar_confianca; senão 'detectado'."""
    return "duvidoso" if confianca < cfg.limiar_confianca else "detectado"


def _residuos_laterais(xy: np.ndarray) -> np.ndarray:
    """Distância assinada de cada ponto à reta de melhor ajuste (mínimos quadrados totais)."""
    centro = xy.mean(axis=0)
    _, _, vt = np.linalg.svd(xy - centro, full_matrices=False)
    normal = np.array([-vt[0][1], vt[0][0]])
    return (xy - centro) @ normal


def marcar_saltos_laterais(trilha: Trilha, cfg: Config) -> Trilha:
    """Marca 'duvidoso' o ponto medido cuja posição lateral difere da mediana local (cfg.janela_mediana,
    em pontos medidos vizinhos) por mais de cfg.limite_variacao_m, depois de remover a tendência (reta
    de melhor ajuste da trilha). Pontos 'interpolado' não são alterados nem entram na mediana.
    A posição nunca é alterada."""
    idx = [i for i, p in enumerate(trilha.pontos) if p.status != "interpolado"]
    if len(idx) < 3:
        return trilha
    xy = np.array([[trilha.pontos[i].x, trilha.pontos[i].y] for i in idx])
    r = _residuos_laterais(xy)
    meia = cfg.janela_mediana // 2
    novos = list(trilha.pontos)
    for k, i in enumerate(idx):
        lo, hi = max(0, k - meia), min(len(idx), k + meia + 1)
        if abs(r[k] - float(np.median(r[lo:hi]))) > cfg.limite_variacao_m and novos[i].status == "detectado":
            novos[i] = replace(novos[i], status="duvidoso")
    return Trilha(pontos=tuple(novos))


def _lateral_da_corda(xy: np.ndarray) -> np.ndarray:
    """Distância assinada de cada ponto interno à corda entre seus vizinhos (0 nas pontas)."""
    e = np.zeros(len(xy))
    a, b, c = xy[:-2], xy[1:-1], xy[2:]
    v = c - a
    norma = np.hypot(v[:, 0], v[:, 1])
    norma[norma == 0] = 1.0
    e[1:-1] = ((b[:, 0] - a[:, 0]) * v[:, 1] - (b[:, 1] - a[:, 1]) * v[:, 0]) / norma
    return e


def _curvatura(xy: np.ndarray) -> np.ndarray:
    """Curvatura de Menger (1/m) em cada ponto interno; 0 nas pontas."""
    k = np.zeros(len(xy))
    a, b, c = xy[:-2], xy[1:-1], xy[2:]
    ab, bc, ca = np.hypot(*(b - a).T), np.hypot(*(c - b).T), np.hypot(*(c - a).T)
    dobro_area = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    den = ab * bc * ca
    den[den == 0] = np.inf
    k[1:-1] = 2.0 * dobro_area / den
    return k


def marcar_saltos_curvos(trilha: Trilha, cfg: Config) -> Trilha:
    """Versão para fileiras em curva (modo_blocos="faixas"): em vez da reta de melhor ajuste da trilha toda,
    mede o desvio lateral de cada ponto medido à corda entre seus vizinhos medidos e o compara com a
    mediana desses desvios numa janela de 5 pontos (a mediana absorve a curvatura, que dá um desvio de
    corda regular). Marca 'duvidoso' o ponto cujo desvio difere da mediana por mais de cfg.limite_variacao_m
    e que é o maior da vizinhança. Se cfg.curvatura_duvidosa_1_m > 0, marca também 'duvidoso' o trecho cuja
    curvatura (Menger, mediana de 3 pontos) passa desse limite: o algoritmo é tido como não confiável ali.
    HIPÓTESE sem fonte lida. A posição nunca é alterada; pontos 'interpolado' não entram."""
    idx = [i for i, p in enumerate(trilha.pontos) if p.status != "interpolado"]
    if len(idx) < 3:
        return trilha
    xy = np.array([[trilha.pontos[i].x, trilha.pontos[i].y] for i in idx])
    e = _lateral_da_corda(xy)
    n = len(idx)
    dev = np.zeros(n)
    for k in range(1, n - 1):
        lo, hi = max(1, k - 2), min(n - 1, k + 3)
        dev[k] = e[k] - float(np.median(e[lo:hi]))
    marca = np.zeros(n, dtype=bool)
    for k in range(1, n - 1):
        viz = [abs(dev[j]) for j in (k - 1, k + 1) if 0 < j < n - 1]
        if abs(dev[k]) > cfg.limite_variacao_m and all(abs(dev[k]) >= v for v in viz):
            marca[k] = True
    if cfg.curvatura_duvidosa_1_m > 0 and n >= 3:
        kap = _curvatura(xy)
        sua = kap.copy()
        for k in range(1, n - 1):
            sua[k] = np.median(kap[max(1, k - 1):min(n - 1, k + 2)])
        marca |= sua > cfg.curvatura_duvidosa_1_m
    novos = list(trilha.pontos)
    for k, i in enumerate(idx):
        if marca[k] and novos[i].status == "detectado":
            novos[i] = replace(novos[i], status="duvidoso")
    return Trilha(pontos=tuple(novos))


def avaliar_trilha(trilha: Trilha, talhao: str, cfg: Config) -> FileiraAvaliada:
    """Monta a geometria (todos os pontos, inclusive duvidosos: posição medida, marcada),
    comprimento_m, confianca_media e frac_duvidosa."""
    if len(trilha.pontos) < 2:
        raise ErroContrato("trilha com menos de dois pontos não forma linha")
    geom = LineString([(p.x, p.y) for p in trilha.pontos])
    n = len(trilha.pontos)
    return FileiraAvaliada(
        talhao=talhao, geometria=geom, pontos=trilha.pontos, comprimento_m=float(geom.length),
        confianca_media=float(np.mean([p.confianca for p in trilha.pontos])),
        frac_duvidosa=sum(p.status == "duvidoso" for p in trilha.pontos) / n)


def avaliar_trilhas(trilhas: list[Trilha], talhao: str, cfg: Config) -> list[FileiraAvaliada]:
    """Aplica marcar_saltos_laterais e avaliar_trilha a todas as trilhas do talhão."""
    marcar = marcar_saltos_curvos if cfg.modo_blocos == "faixas" else marcar_saltos_laterais
    return [avaliar_trilha(marcar(t, cfg), talhao, cfg) for t in trilhas]
