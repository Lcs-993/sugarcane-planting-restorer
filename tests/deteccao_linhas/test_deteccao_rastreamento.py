import math

import pytest
from shapely.geometry import box

from deteccao_linhas.config import Config
from deteccao_linhas.rastreamento import rastrear, rastrear_com_descartes
from deteccao_linhas.tipos import Bloco, PosicaoFileira, ResultadoPente


def _res(k, xs, conf=0.9, az_graus=0.0, x_shift=0.0):
    """Bloco k ao longo de y (u norte), 10 m, posições nos x dados."""
    bl = Bloco(f"B{k:03d}", "R1", (0.0, 0.0), (0.0, 1.0), (-1.0, 0.0), 10.0 * k, 10.0, -50.0, 50.0,
               10.0 * k + 5.0, box(-60, 10 * k, 60, 10 * k + 10))
    pos = tuple(PosicaoFileira(bl.id_bloco, -x, x, 10 * k + 5.0, 0.48, 0.8, 1.0, 1.0, 1.5, False, conf) for x in xs)
    return ResultadoPente(bl, pos, 0.0)


CFG = Config(comprimento_min_fileira_m=30.0)


def test_fileiras_retas():
    rs = [_res(k, [0.0, 1.5, 3.0]) for k in range(8)]
    tr = rastrear(rs, CFG)
    assert len(tr) == 3
    for t in tr:
        assert len(t.pontos) == 8 and all(p.status == "detectado" for p in t.pontos)
        assert t.pontos[0].posicao_m == 0.0 and t.pontos[-1].posicao_m == pytest.approx(70.0)
        assert len({round(p.x, 6) for p in t.pontos}) == 1


def test_falha_curta_vira_interpolado():
    rs = [_res(k, [0.0, 1.5] if k not in (3, 4) else [1.5]) for k in range(8)]
    tr = rastrear(rs, CFG)
    assert len(tr) == 2
    t = [t for t in tr if t.pontos[0].x == 0.0][0]
    assert [p.status for p in t.pontos].count("interpolado") == 2
    interp = [p for p in t.pontos if p.status == "interpolado"]
    assert [p.id_bloco for p in interp] == ["B003", "B004"]
    assert all(abs(p.x) < 1e-9 for p in interp)
    assert all(p.confianca == pytest.approx(0.9) for p in interp)


def test_falha_longa_encerra_sem_projetar():
    # 4 blocos sem posição (> max_blocos_falha=3): a trilha termina em B003 e nada é projetado
    rs = [_res(k, [0.0] if k not in (4, 5, 6, 7) else []) for k in range(12)]
    tr, desc = rastrear_com_descartes(rs, Config(comprimento_min_fileira_m=10.0))
    tr = sorted(tr, key=lambda t: t.pontos[0].id_bloco)
    assert [len(t.pontos) for t in tr] == [4, 4]
    assert [t.pontos[-1].id_bloco for t in tr] == ["B003", "B011"]
    assert all(p.status != "interpolado" for t in tr for p in t.pontos)
    # falha de exatamente 3 blocos ainda é reconfirmada
    rs3 = [_res(k, [0.0] if k not in (4, 5, 6) else []) for k in range(10)]
    tr3 = rastrear(rs3, Config(comprimento_min_fileira_m=10.0))
    assert len(tr3) == 1 and [p.status for p in tr3[0].pontos].count("interpolado") == 3


def test_salto_lateral_alem_da_tolerancia_inicia_nova_trilha():
    rs = [_res(k, [0.0]) for k in range(5)] + [_res(k, [0.5]) for k in range(5, 10)]
    tr = rastrear(rs, Config(comprimento_min_fileira_m=10.0))
    assert len(tr) == 2
    tr_ok = rastrear([_res(k, [0.0]) for k in range(5)] + [_res(k, [0.25]) for k in range(5, 10)],
                     Config(comprimento_min_fileira_m=10.0))
    assert len(tr_ok) == 1 and len(tr_ok[0].pontos) == 10


def test_trilha_curta_descartada_e_contada():
    rs = [_res(k, [0.0, 1.5]) for k in range(2)] + [_res(k, [0.0]) for k in range(2, 8)]
    tr, desc = rastrear_com_descartes(rs, CFG)  # mínimo 30 m
    assert len(tr) == 1 and desc == 1


def test_um_para_um():
    # duas posições próximas (0,10 e 0,25) para uma única trilha: só uma casa, a outra inicia trilha
    rs = [_res(k, [0.0]) for k in range(4)] + [_res(k, [0.05, 0.25]) for k in range(4, 8)]
    tr, desc = rastrear_com_descartes(rs, Config(comprimento_min_fileira_m=5.0))
    assert len(tr) == 2
    assert max(len(t.pontos) for t in tr) == 8
    assert sorted(len(t.pontos) for t in tr) == [4, 8]


def test_duvidoso_entra_na_trilha_com_status():
    rs = [_res(k, [0.0], conf=0.2 if k == 2 else 0.9) for k in range(6)]
    tr = rastrear(rs, Config(comprimento_min_fileira_m=10.0))
    assert [p.status for p in tr[0].pontos] == ["detectado", "detectado", "duvidoso", "detectado", "detectado", "detectado"]


def test_ordem_independente_da_entrada():
    rs = [_res(k, [0.0, 1.5]) for k in range(6)]
    a = rastrear(rs, CFG)
    b = rastrear(list(reversed(rs)), CFG)
    assert [len(t.pontos) for t in a] == [len(t.pontos) for t in b] == [6, 6]
