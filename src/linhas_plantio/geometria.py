"""Auxiliares de geometria de linhas: posição, tangente e normal esquerda ao longo de uma linha."""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

# Distância usada para estimar a tangente local por diferença finita. Escolha técnica
# (não é parâmetro agronômico); a tangente é a da corda entre s - delta e s + delta.
DELTA_TANGENTE_M = 0.5


def posicao_e_tangente(linha: LineString, s: float) -> tuple[float, float, tuple[float, float]]:
    """(x, y, tangente unitária) no ponto a distância `s` do início, no sentido de digitalização."""
    comp = linha.length
    s = float(min(max(s, 0.0), comp))
    p = linha.interpolate(s)
    a = linha.interpolate(max(s - DELTA_TANGENTE_M, 0.0))
    b = linha.interpolate(min(s + DELTA_TANGENTE_M, comp))
    dx, dy = b.x - a.x, b.y - a.y
    n = float(np.hypot(dx, dy))
    if n == 0.0:
        raise ValueError("linha degenerada: comprimento nulo")
    return p.x, p.y, (dx / n, dy / n)


def normal_esquerda(tangente: tuple[float, float]) -> tuple[float, float]:
    """Vetor unitário à esquerda do sentido de digitalização (rotação de +90 graus)."""
    return (-tangente[1], tangente[0])
