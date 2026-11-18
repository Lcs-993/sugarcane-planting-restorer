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
    return [avaliar_trilha(marcar_saltos_laterais(t, cfg), talhao, cfg) for t in trilhas]
