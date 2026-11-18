"""Testes do módulo reconstrucao.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import numpy as np
import pytest
from shapely.geometry import LineString

from linhas_plantio.config import Config
from linhas_plantio.reconstrucao import (
    interpolar_trechos, montar_perfil, reconstruir_linha, reconstruir_passada, suavizar_perfil,
)
from linhas_plantio.tipos import ErroContrato, EstacaoDesvio, Passada

CFG = Config()
PASSADA = Passada("P0", "T1", LineString([(0, 0), (80, 0)]))


def est(i, desvio=0.3, status="detectado", conf=0.9):
    return EstacaoDesvio("P0", "T1", 10.0 * i, 10.0 * i, 0.0, (0.0, 1.0), desvio, 1.5, 0.48, 0.48, status, conf)


def serie(desvios, status=None):
    status = status or {}
    return [est(i, v, status.get(i, "detectado" if v is not None else "duvidoso")) for i, v in enumerate(desvios)]


def test_montar_perfil_ignora_duvidosas_e_sem_valor():
    s, d = montar_perfil(serie([0.1, None, 0.3, 0.9, 0.5], {3: "duvidoso"}))
    assert s.tolist() == [0.0, 20.0, 40.0] and d.tolist() == [0.1, 0.3, 0.5]


def test_suavizar_reproduz_reta_e_retira_pico():
    s = np.arange(0.0, 90.0, 10.0)
    f = suavizar_perfil(s, 0.005 * s, CFG)
    assert f(np.array([25.0]))[0] == pytest.approx(0.125, abs=1e-6)
    d = np.full_like(s, 0.3)
    d[4] = 1.0  # pico isolado: a mediana de 3 o remove
    assert suavizar_perfil(s, d, CFG)(np.array([40.0]))[0] == pytest.approx(0.3, abs=1e-6)


def test_suavizar_com_duas_estacoes_e_erro_com_uma():
    f = suavizar_perfil(np.array([0.0, 10.0]), np.array([0.0, 0.2]), CFG)
    assert f(np.array([5.0]))[0] == pytest.approx(0.1)
    with pytest.raises(ErroContrato, match="menos de 2"):
        suavizar_perfil(np.array([0.0]), np.array([0.1]), CFG)


def test_interpolacao_marca_trecho_sem_deteccao():
    ests = serie([0.1, 0.1, None, None, 0.1, 0.1, 0.1, 0.1, 0.1])
    s, d = montar_perfil(ests)
    out = interpolar_trechos(ests, suavizar_perfil(s, d, CFG))
    assert [e.status for e in out[2:4]] == ["interpolado", "interpolado"]
    assert all(e.desvio_m == pytest.approx(0.1) for e in out)
    assert all(e.confianca <= 0.3 for e in out[2:4])


def test_sem_estacao_boa_nas_duas_extremidades_nao_inventa_valor():
    ests = serie([None, None, 0.1, 0.1, 0.1, 0.1, 0.1, None, None])
    s, d = montar_perfil(ests)
    out = interpolar_trechos(ests, suavizar_perfil(s, d, CFG))
    for i in (0, 1, 7, 8):
        assert out[i].status == "duvidoso" and out[i].desvio_m is None
    assert out[2].status == "detectado"


def test_reprovada_pela_qualidade_mantem_duvidoso_com_valor_do_perfil():
    ests = serie([0.1, 0.1, 0.9, 0.1, 0.1], {2: "duvidoso"})
    s, d = montar_perfil(ests)
    out = interpolar_trechos(ests, suavizar_perfil(s, d, CFG))
    assert out[2].status == "duvidoso" and out[2].desvio_m == pytest.approx(0.1)


def test_reconstruir_linha_desloca_a_esquerda():
    ests = serie([0.3] * 9)
    linha = reconstruir_linha(PASSADA, ests)
    c = np.asarray(linha.coords)
    assert len(c) == 9 and np.allclose(c[:, 1], 0.3) and c[0, 0] == 0 and c[-1, 0] == 80
    direita = reconstruir_linha(PASSADA, serie([-0.2] * 9))
    assert np.allclose(np.asarray(direita.coords)[:, 1], -0.2)


def test_sem_valor_mantem_linha_projetada():
    assert reconstruir_linha(PASSADA, serie([None] * 9)).equals(PASSADA.geometria)
    ests = serie([None, 0.3, 0.3, 0.3, None])
    c = np.asarray(reconstruir_linha(PASSADA, ests).coords)
    assert c[0, 1] == 0.0 and c[-1, 1] == 0.0  # pontas sem valor ficam na linha projetada


def test_reconstruir_passada_fracoes_e_revisao():
    r = reconstruir_passada(PASSADA, serie([0.1, 0.1, None, 0.1, 0.1, None, None, 0.1, 0.1]), CFG)
    assert r.frac_interpolada == pytest.approx(3 / 9) and r.frac_duvidosa == 0.0 and not r.revisao_manual
    r2 = reconstruir_passada(PASSADA, serie([None, None, None, 0.1, 0.1, 0.1, 0.1, 0.1, None]), CFG)
    assert r2.frac_duvidosa == pytest.approx(4 / 9) and r2.revisao_manual


def test_menos_de_duas_boas_vai_para_revisao():
    r = reconstruir_passada(PASSADA, serie([None, None, 0.2, None, None, None, None, None, None]), CFG)
    assert all(e.status == "duvidoso" and e.desvio_m is None for e in r.estacoes)
    assert r.revisao_manual and r.frac_duvidosa == 1.0 and r.linha_corrigida.equals(PASSADA.geometria)
