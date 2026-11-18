"""Testes do módulo desvio.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import pytest

from linhas_plantio.config import Config
from linhas_plantio.desvio import calcular_desvio_estacao, calcular_desvios
from linhas_plantio.tipos import DeteccaoEstacao, Passada
from shapely.geometry import LineString

CFG = Config()


def det(t_esq, t_dir, le=0.48, ld=0.48, ke=1.0, kd=0.8, s=0.0):
    return DeteccaoEstacao("P0", s, 0.0, 0.0, (0.0, 1.0), t_esq, t_dir,
                           le if t_esq is not None else None, ld if t_dir is not None else None, ke, kd)


def test_eixo_a_esquerda_e_positivo():
    e = calcular_desvio_estacao(det(1.05, -0.45), "T1", CFG)  # eixo real 0,30 m à esquerda da linha
    assert e.desvio_m == pytest.approx(0.30)
    assert e.espacamento_gemeas_m == pytest.approx(1.50)
    assert e.status == "detectado" and e.confianca == pytest.approx(0.8) and e.talhao == "T1"


def test_eixo_a_direita_e_negativo():
    assert calcular_desvio_estacao(det(0.55, -0.95), "T1", CFG).desvio_m == pytest.approx(-0.20)


def test_so_uma_fileira_e_estimada():
    esq = calcular_desvio_estacao(det(1.05, None), "T1", CFG)
    assert esq.status == "estimado" and esq.desvio_m == pytest.approx(0.30) and esq.espacamento_gemeas_m is None
    dir_ = calcular_desvio_estacao(det(None, -0.45), "T1", CFG)
    assert dir_.status == "estimado" and dir_.desvio_m == pytest.approx(0.30)


def test_nenhuma_fileira_e_duvidosa_sem_valor():
    e = calcular_desvio_estacao(det(None, None), "T1", CFG)
    assert e.status == "duvidoso" and e.desvio_m is None and e.confianca == 0.0


def test_calcular_desvios_usa_talhao_da_passada():
    p = Passada("P0", "T9", LineString([(0, 0), (20, 0)]))
    out = calcular_desvios(p, [det(0.75, -0.75, s=0.0), det(0.75, -0.75, s=10.0)], CFG)
    assert [e.talhao for e in out] == ["T9", "T9"] and [e.estacao_m for e in out] == [0.0, 10.0]
