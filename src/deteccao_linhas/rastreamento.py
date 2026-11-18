"""Liga posições de blocos consecutivos em fileiras contínuas (docs/interfaces-deteccao.md, seção 6.6).

Decisões de implementação (hipóteses, sem fonte lida):
- processa blocos em ordem de s_global_m; para cada bloco, as trilhas "elegíveis" são as que ficam atrás
  dele (0 < ds <= (max_blocos_falha + 1) * passo_bloco_m + comprimento_bloco_m / 2; no modo "faixas" o passo é
  cfg.passo_efetivo_m e o limite de falhas mantém os mesmos metros (cfg.max_falhas_efetivas)) e cujo rastro projetado,
  no intervalo s do bloco, toca o polígono do bloco (com folga de tolerancia_ligacao_m);
- projeção do último ponto da trilha ao bloco: ao longo da direção média entre a do último bloco e a do atual;
- associação um-para-um por atribuição de custo mínimo (distância lateral no quadro do bloco atual), aceita
  se <= cfg.tolerancia_ligacao_m;
- trilha elegível sem associação conta uma falha; passando de cfg.max_blocos_falha é encerrada no último ponto
  detectado (nada projetado é mantido). Reconfirmada, os blocos intermediários viram pontos 'interpolado'
  (interpolação linear; confiança = mínima dos dois vizinhos);
- trilhas mais curtas que cfg.comprimento_min_fileira_m são descartadas e contadas (rastrear_com_descartes).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import LineString

from .config import Config
from .qualidade import classificar_ponto
from .tipos import Bloco, PontoFileira, ResultadoPente, Trilha

CUSTO_PROIBIDO = 1e6


@dataclass
class _Ativa:
    pontos: list[tuple[float, float, str, float, str]] = field(default_factory=list)  # x, y, status, conf, bloco
    u_ultimo: tuple[float, float] = (0.0, 1.0)
    falhas: list[Bloco] = field(default_factory=list)  # blocos sem posição desde o último ponto

    @property
    def ultimo(self) -> tuple[float, float]:
        return self.pontos[-1][0], self.pontos[-1][1]


def _base_meio(b: Bloco) -> tuple[float, float]:
    s_mid = b.s0_m + b.comprimento_m / 2.0
    return b.origem[0] + s_mid * b.u[0], b.origem[1] + s_mid * b.u[1]


def _projetar(a: _Ativa, b: Bloco) -> tuple[float, tuple[float, float]]:
    """(ds, ponto projetado) do último ponto da trilha ao bloco b; direção média das duas."""
    ux, uy = a.u_ultimo[0] + b.u[0], a.u_ultimo[1] + b.u[1]
    norma = math.hypot(ux, uy) or 1.0
    ux, uy = ux / norma, uy / norma
    px, py = a.ultimo
    bx, by = _base_meio(b)
    ds = (bx - px) * b.u[0] + (by - py) * b.u[1]
    cos = ux * b.u[0] + uy * b.u[1]
    passo = ds / cos if cos > 1e-6 else ds
    return ds, (px + passo * ux, py + passo * uy)


def _comprimento(pontos: list[tuple]) -> float:
    return float(sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pontos, pontos[1:])))


def _fechar(a: _Ativa) -> Trilha | None:
    if not a.pontos:
        return None
    acum = 0.0
    saida = []
    for i, (x, y, st, conf, bid) in enumerate(a.pontos):
        if i:
            acum += math.hypot(x - a.pontos[i - 1][0], y - a.pontos[i - 1][1])
        saida.append(PontoFileira(id_bloco=bid, x=x, y=y, posicao_m=acum, status=st, confianca=conf))  # type: ignore[arg-type]
    return Trilha(pontos=tuple(saida))


def rastrear_com_descartes(resultados: list[ResultadoPente], cfg: Config) -> tuple[list[Trilha], int]:
    """Como `rastrear`, mas devolve também quantas trilhas foram descartadas por comprimento mínimo."""
    ordenados = sorted(resultados, key=lambda r: (r.bloco.s_global_m, r.bloco.id_bloco))
    ativas: list[_Ativa] = []
    encerradas: list[_Ativa] = []
    ds_max_extra = cfg.comprimento_bloco_m / 2.0
    tol = cfg.tolerancia_ligacao_m
    for res in ordenados:
        b = res.bloco
        ref_poli = b.nucleo if b.nucleo is not None else b.poligono  # faixas: só o núcleo conta
        poli = ref_poli.buffer(tol) if ref_poli is not None else None
        eleg: list[tuple[_Ativa, tuple[float, float]]] = []
        for a in ativas:
            ds, proj = _projetar(a, b)
            if ds <= 0 or ds > (cfg.max_falhas_efetivas + 1) * cfg.passo_efetivo_m + ds_max_extra:
                continue
            if poli is not None:
                # o rastro da fileira projetada ao longo do intervalo s do bloco deve tocar o polígono
                # (o ponto no meio do intervalo pode cair fora de um bloco recortado pela região)
                m = b.comprimento_m / 2.0
                rastro = LineString([(proj[0] - m * b.u[0], proj[1] - m * b.u[1]),
                                     (proj[0] + m * b.u[0], proj[1] + m * b.u[1])])
                if not poli.intersects(rastro):
                    continue
            eleg.append((a, proj))
        pos = list(res.posicoes)
        casadas: dict[int, int] = {}
        if eleg and pos:
            custo = np.full((len(eleg), len(pos)), CUSTO_PROIBIDO)
            for i, (a, proj) in enumerate(eleg):
                for j, q in enumerate(pos):
                    lat = abs((q.x - proj[0]) * b.n[0] + (q.y - proj[1]) * b.n[1])
                    if lat <= tol:
                        custo[i, j] = lat
            for i, j in zip(*linear_sum_assignment(custo)):
                if custo[i, j] < CUSTO_PROIBIDO:
                    casadas[int(i)] = int(j)
        usadas = set(casadas.values())
        for i, (a, proj) in enumerate(eleg):
            if i in casadas:
                q = pos[casadas[i]]
                if a.falhas:  # reconfirmada: preenche os blocos intermediários por interpolação
                    x0, y0, _, c0, _ = a.pontos[-1]
                    ux, uy = b.u
                    den = (q.x - x0) * ux + (q.y - y0) * uy
                    for fb in a.falhas:
                        bx, by = _base_meio(fb)
                        f = ((bx - x0) * fb.u[0] + (by - y0) * fb.u[1]) / den if abs(den) > 1e-9 else 0.5
                        f = min(1.0, max(0.0, f))
                        a.pontos.append((x0 + f * (q.x - x0), y0 + f * (q.y - y0), "interpolado",
                                         min(c0, q.confianca), fb.id_bloco))
                    a.falhas = []
                a.pontos.append((q.x, q.y, classificar_ponto(q.confianca, cfg), q.confianca, b.id_bloco))
                a.u_ultimo = b.u
            else:
                a.falhas.append(b)
                if len(a.falhas) > cfg.max_falhas_efetivas:
                    a.falhas = []  # nada projetado é mantido
                    encerradas.append(a)
                    ativas.remove(a)
        for j, q in enumerate(pos):
            if j not in usadas:
                n = _Ativa(u_ultimo=b.u)
                n.pontos.append((q.x, q.y, classificar_ponto(q.confianca, cfg), q.confianca, b.id_bloco))
                ativas.append(n)
    encerradas.extend(ativas)
    trilhas: list[Trilha] = []
    descartadas = 0
    for a in encerradas:
        a.falhas = []
        if _comprimento(a.pontos) < cfg.comprimento_min_fileira_m:
            descartadas += 1
            continue
        t = _fechar(a)
        if t is not None:
            trilhas.append(t)
    return trilhas, descartadas


def rastrear(resultados: list[ResultadoPente], cfg: Config) -> list[Trilha]:
    """Liga posições de blocos consecutivos (ordem de s_global_m) em fileiras contínuas. Não numera."""
    return rastrear_com_descartes(resultados, cfg)[0]
