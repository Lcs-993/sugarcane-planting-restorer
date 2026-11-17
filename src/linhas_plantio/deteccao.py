"""Módulo deteccao (skill perfil-transversal): amostra perfis perpendiculares à linha de piloto
projetada e localiza o centro de cada faixa de cana. A linha projetada é o guia; não se detecta
fileira do zero (docs/interfaces-fase1.md, seção 6.4)."""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from .config import Config
from .geometria import normal_esquerda, posicao_e_tangente
from .segmentacao import FonteBinaria
from .tipos import DeteccaoEstacao, ErroContrato, Passada, PerfilTransversal

# HIPÓTESE (sem fonte lida): fração mínima de vegetação no perfil para um ponto contar como faixa.
LIMIAR_VEGETACAO_PERFIL = 0.5
# HIPÓTESE (sem fonte lida): largura mínima, em metros, de um trecho contínuo para ser candidato a faixa.
LARGURA_MINIMA_CANDIDATA_M = 0.10
# HIPÓTESE (sem fonte lida): fração mínima de amostras válidas ao longo da linha para o ponto do perfil existir.
FRACAO_VALIDA_MINIMA = 0.5


def gerar_estacoes(linha: LineString, espacamento_m: float) -> np.ndarray:
    """Distâncias ao longo da linha: 0, e, 2e, ... e a extremidade final sempre incluída."""
    comp = linha.length
    s = np.arange(0.0, comp, espacamento_m)
    if s.size == 0 or comp - s[-1] > 1e-6:
        s = np.append(s, comp)
    return s


def _meia_extensao_m(cfg: Config) -> float:
    return cfg.semijanela_busca_m + cfg.largura_faixa_max_m / 2.0 + cfg.tolerancia_largura_m


def amostrar_perfil(
    fonte: FonteBinaria,
    x: float,
    y: float,
    normal_esq: tuple[float, float],
    tangente: tuple[float, float],
    cfg: Config,
) -> PerfilTransversal:
    """Perfil perpendicular à linha cobrindo as duas fileiras projetadas com a semijanela de busca
    e a meia-largura da faixa. Cada ponto do perfil é a média da vegetação em
    cfg.comprimento_amostra_m ao longo da linha. Lê só a janela necessária.

    Pontos sem dado (nodata, fora do polígono útil ou fora do raster) ficam NaN.
    """
    passo = fonte.resolucao_m
    t_max = cfg.espacamento_gemeas_ref_m / 2.0 + _meia_extensao_m(cfg)
    n_t = int(np.ceil(t_max / passo))
    t = np.arange(-n_t, n_t + 1) * passo  # grade simétrica em torno da linha projetada (inclui t = 0)
    n_u = max(int(round(cfg.comprimento_amostra_m / passo)), 1)
    u = (np.arange(n_u) - (n_u - 1) / 2.0) * passo
    T, U = np.meshgrid(t, u, indexing="ij")
    X = x + T * normal_esq[0] + U * tangente[0]
    Y = y + T * normal_esq[1] + U * tangente[1]
    bounds = (X.min() - passo, Y.min() - passo, X.max() + passo, Y.max() + passo)
    vazio = PerfilTransversal(t_m=t, valores=np.full(t.shape, np.nan))
    try:
        jan = fonte.ler_janela(bounds)
    except ErroContrato:
        return vazio  # estação fora do raster: sem dado, não é erro
    tr = jan.transform
    cols = np.floor((X - tr.c) / tr.a).astype(int)
    lins = np.floor((Y - tr.f) / tr.e).astype(int)
    h, w = jan.valores.shape
    dentro = (cols >= 0) & (cols < w) & (lins >= 0) & (lins < h)
    cols_c, lins_c = np.clip(cols, 0, w - 1), np.clip(lins, 0, h - 1)
    valido = dentro & jan.validade[lins_c, cols_c]
    val = np.where(valido, jan.valores[lins_c, cols_c].astype(float), 0.0)
    n_val = valido.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        media = val.sum(axis=1) / n_val
    media = np.where(n_val >= FRACAO_VALIDA_MINIMA * n_u, media, np.nan)
    return PerfilTransversal(t_m=t, valores=media)


def _candidatas(perfil: PerfilTransversal) -> list[tuple[float, float, float]]:
    """Trechos contínuos acima do limiar: (centro_t, largura, vegetação média)."""
    t, v = perfil.t_m, perfil.valores
    passo = float(t[1] - t[0])
    ok = np.nan_to_num(v, nan=0.0) >= LIMIAR_VEGETACAO_PERFIL
    saida: list[tuple[float, float, float]] = []
    i = 0
    n = ok.size
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        largura = (j - i + 1) * passo
        if largura >= LARGURA_MINIMA_CANDIDATA_M:
            saida.append(((t[i] + t[j]) / 2.0, largura, float(np.nanmean(v[i : j + 1]))))
        i = j + 1
    return saida


def localizar_centros(perfil: PerfilTransversal, cfg: Config) -> tuple[
    tuple[float | None, float | None, float],
    tuple[float | None, float | None, float],
]:
    """Procura o centro de cada faixa em [+0,75 ± semijanela] e [-0,75 ± semijanela].

    Devolve (centro_t, largura, confiança) para a fileira esquerda e para a direita. Sem pico
    confiável devolve (None, None, 0.0); nunca preenche.

    Confiança (fórmula HIPÓTESE, sem fonte lida): vegetação média no trecho vezes um fator de
    largura que cai linearmente de 1 (largura igual à referência, ponto médio de 45 a 50 cm) a 0
    (desvio de 100 % da referência).
    """
    cand = _candidatas(perfil)
    ref_larg = (cfg.largura_faixa_min_m + cfg.largura_faixa_max_m) / 2.0

    def escolher(t0: float) -> tuple[float | None, float | None, float]:
        dentro = [c for c in cand if abs(c[0] - t0) <= cfg.semijanela_busca_m]
        if not dentro:
            return (None, None, 0.0)
        centro, largura, media = max(dentro, key=lambda c: c[1] * c[2])
        fator = max(0.0, 1.0 - abs(largura - ref_larg) / ref_larg)
        return (float(centro), float(largura), float(min(1.0, media * fator)))

    meio = cfg.espacamento_gemeas_ref_m / 2.0
    return escolher(+meio), escolher(-meio)


def detectar_passada(passada: Passada, fonte: FonteBinaria, cfg: Config) -> list[DeteccaoEstacao]:
    """Uma DeteccaoEstacao por estação da passada."""
    saida: list[DeteccaoEstacao] = []
    for s in gerar_estacoes(passada.geometria, cfg.espacamento_estacoes_m):
        x, y, tang = posicao_e_tangente(passada.geometria, float(s))
        normal = normal_esquerda(tang)
        perfil = amostrar_perfil(fonte, x, y, normal, tang, cfg)
        (c_esq, l_esq, k_esq), (c_dir, l_dir, k_dir) = localizar_centros(perfil, cfg)
        saida.append(
            DeteccaoEstacao(
                id_passada=passada.id_passada, estacao_m=float(s), x=x, y=y, normal_esq=normal,
                t_esq_m=c_esq, t_dir_m=c_dir, largura_esq_m=l_esq, largura_dir_m=l_dir,
                confianca_esq=k_esq, confianca_dir=k_dir,
            )
        )
    return saida
