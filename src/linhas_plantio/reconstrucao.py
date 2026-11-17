"""Módulo reconstrucao (skill suavizacao-deriva): suaviza o perfil de desvio lateral ao longo da
passada e reconstrói a linha corrigida (docs/interfaces-fase1.md, seção 6.7).

O deslocamento não é um valor fixo por passada: é um perfil ao longo da linha.
Nunca se inventa desvio em trecho sem estação boa nas duas extremidades: ele fica 'duvidoso'.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

import numpy as np
from scipy.interpolate import UnivariateSpline
from scipy.ndimage import median_filter
from shapely.geometry import LineString

from .config import Config
from .geometria import normal_esquerda, posicao_e_tangente
from .qualidade import TETO_CONFIANCA_DUVIDOSA
from .tipos import ErroContrato, EstacaoDesvio, Passada, ResultadoPassada

# HIPÓTESE (sem fonte lida): confiança atribuída a uma estação interpolada.
CONFIANCA_INTERPOLADA = 0.3

_BOAS = ("detectado", "estimado")


def _boa(e: EstacaoDesvio) -> bool:
    return e.status in _BOAS and e.desvio_m is not None


def montar_perfil(estacoes: list[EstacaoDesvio]) -> tuple[np.ndarray, np.ndarray]:
    """(estacao_m, desvio_m) só das estações boas (detectado ou estimado, com desvio_m), em ordem."""
    boas = sorted((e for e in estacoes if _boa(e)), key=lambda e: e.estacao_m)
    return (np.array([e.estacao_m for e in boas], dtype=float),
            np.array([e.desvio_m for e in boas], dtype=float))


def suavizar_perfil(s: np.ndarray, d: np.ndarray, cfg: Config) -> Callable[[np.ndarray], np.ndarray]:
    """Filtro de mediana (cfg.janela_mediana) seguido de spline (cfg.fator_spline).

    Devolve a função desvio(estacao_m); fora do intervalo das estações boas o valor é o da
    extremidade (sem extrapolar). Com duas estações a spline vira reta.

    Raises:
        ErroContrato: menos de 2 estações boas.
    """
    s = np.asarray(s, dtype=float)
    d = np.asarray(d, dtype=float)
    n = s.size
    if n < 2:
        raise ErroContrato("menos de 2 estações boas: não há perfil de desvio para suavizar")
    janela = min(cfg.janela_mediana, n if n % 2 == 1 else n - 1)
    d_f = median_filter(d, size=janela, mode="nearest") if janela > 1 else d.copy()
    s0, s1 = float(s[0]), float(s[-1])
    if n == 2:
        return lambda x: np.interp(np.asarray(x, dtype=float), s, d_f)
    # fator_spline é repassado como suavização `s` da UnivariateSpline (soma dos quadrados dos
    # resíduos, m²): 0 interpola as estações. HIPÓTESE de configuração, sem fonte lida.
    spl = UnivariateSpline(s, d_f, k=min(3, n - 1), s=cfg.fator_spline)
    return lambda x: np.asarray(spl(np.clip(np.asarray(x, dtype=float), s0, s1)), dtype=float)


def interpolar_trechos(
    estacoes: list[EstacaoDesvio],
    perfil: Callable[[np.ndarray], np.ndarray],
) -> list[EstacaoDesvio]:
    """Estações sem detecção utilizável, com estação boa nas duas extremidades, recebem desvio_m
    do perfil e status 'interpolado'. Estações reprovadas pela qualidade mantêm 'duvidoso' (com
    desvio_m do perfil se interpolável). Sem estação boa nas duas extremidades: desvio_m None e
    'duvidoso'. As estações boas recebem o valor suavizado."""
    s_boas = [e.estacao_m for e in estacoes if _boa(e)]
    primeira, ultima = min(s_boas), max(s_boas)
    saida: list[EstacaoDesvio] = []
    for e in estacoes:
        valor = float(perfil(np.array([e.estacao_m]))[0])
        if _boa(e):
            saida.append(replace(e, desvio_m=valor))
            continue
        dentro = primeira <= e.estacao_m <= ultima
        if e.desvio_m is None:  # sem detecção utilizável
            if dentro:
                saida.append(replace(e, desvio_m=valor, status="interpolado", confianca=CONFIANCA_INTERPOLADA))
            else:
                saida.append(replace(e, desvio_m=None, status="duvidoso", confianca=0.0))
        else:  # detectada, mas reprovada pela qualidade
            saida.append(replace(
                e, desvio_m=valor if dentro else None, status="duvidoso",
                confianca=min(e.confianca, TETO_CONFIANCA_DUVIDOSA) if dentro else 0.0,
            ))
    return saida


def reconstruir_linha(passada: Passada, estacoes: list[EstacaoDesvio]) -> LineString:
    """Desloca cada vértice da linha projetada (e cada estação) pela normal esquerda com o desvio
    interpolado em estacao_m. Onde não há valor de desvio o deslocamento é 0 (linha projetada
    mantida) e o trecho fica marcado 'duvidoso' nas estações."""
    linha = passada.geometria
    com_valor = sorted((e for e in estacoes if e.desvio_m is not None), key=lambda e: e.estacao_m)
    if not com_valor:
        return linha
    s_e = np.array([e.estacao_m for e in com_valor])
    d_e = np.array([e.desvio_m for e in com_valor])
    coords = np.asarray(linha.coords)[:, :2]
    s_vert = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])
    s_todos = np.unique(np.round(np.concatenate([s_vert, s_e]), 9))
    pontos = []
    for s in s_todos:
        x, y, tang = posicao_e_tangente(linha, float(s))
        nx, ny = normal_esquerda(tang)
        d = float(np.interp(s, s_e, d_e)) if s_e[0] <= s <= s_e[-1] else 0.0
        pontos.append((x + d * nx, y + d * ny))
    return LineString(pontos)


def reconstruir_passada(passada: Passada, estacoes: list[EstacaoDesvio], cfg: Config) -> ResultadoPassada:
    """Suaviza, interpola, reconstrói a linha e calcula frac_duvidosa, frac_interpolada e
    revisao_manual (frac_duvidosa > fracao_duvidosa_revisao).

    Com menos de 2 estações boas não há perfil: todas as estações ficam 'duvidoso' sem valor, a
    linha projetada é mantida e a passada vai para revisão manual.
    """
    s, d = montar_perfil(estacoes)
    if s.size < 2:
        finais = [replace(e, desvio_m=None, status="duvidoso", confianca=0.0) for e in estacoes]
        linha = passada.geometria
    else:
        finais = interpolar_trechos(estacoes, suavizar_perfil(s, d, cfg))
        linha = reconstruir_linha(passada, finais)
    n = max(len(finais), 1)
    frac_d = sum(e.status == "duvidoso" for e in finais) / n
    frac_i = sum(e.status == "interpolado" for e in finais) / n
    return ResultadoPassada(
        passada=passada, estacoes=tuple(finais), linha_corrigida=linha,
        frac_duvidosa=frac_d, frac_interpolada=frac_i,
        revisao_manual=frac_d > cfg.fracao_duvidosa_revisao,
    )
