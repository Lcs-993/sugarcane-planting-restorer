"""Confiança e avaliação das trilhas (docs/interfaces-deteccao.md, seção 6.7)."""
from __future__ import annotations

from .config import Config
from .tipos import PosicaoFileira, Status


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
