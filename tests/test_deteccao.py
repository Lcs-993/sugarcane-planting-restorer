"""Testes do módulo deteccao (e geometria).

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import numpy as np
import pytest
from shapely.geometry import LineString

import sinteticos as syn
from linhas_plantio.config import Config
from linhas_plantio.deteccao import amostrar_perfil, detectar_passada, gerar_estacoes, localizar_centros
from linhas_plantio.geometria import normal_esquerda, posicao_e_tangente
from linhas_plantio.tipos import PerfilTransversal

CFG = Config()


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    caso = syn.gerar_caso(tmp_path_factory.mktemp("det"), syn.deriva_constante(0.30))
    dados, fonte, fb = syn.preparar(caso, CFG)
    yield caso, dados, fb
    fonte.fechar()


def test_gerar_estacoes():
    assert gerar_estacoes(LineString([(0, 0), (80, 0)]), 10).tolist() == [0, 10, 20, 30, 40, 50, 60, 70, 80]
    s = gerar_estacoes(LineString([(0, 0), (85, 0)]), 10)
    assert s[-1] == 85 and len(s) == 10  # extremidade final sempre incluída


def test_geometria_tangente_e_normal_esquerda():
    x, y, t = posicao_e_tangente(LineString([(0, 0), (10, 0)]), 5.0)
    assert (x, y) == (5.0, 0.0) and t == pytest.approx((1.0, 0.0))
    assert normal_esquerda(t) == pytest.approx((0.0, 1.0))  # esquerda de quem vai para leste é norte


def test_localizar_centros_em_perfil_ideal():
    t = np.round(np.arange(-1.5, 1.5, 0.03), 4)
    v = np.zeros_like(t)
    v[(t >= 0.80 - 0.24) & (t <= 0.80 + 0.24)] = 1.0  # esquerda deslocada +0,05
    v[(t >= -0.75 - 0.24) & (t <= -0.75 + 0.24)] = 1.0
    (ce, le, ke), (cd, ld, kd) = localizar_centros(PerfilTransversal(t, v), CFG)
    assert ce == pytest.approx(0.80, abs=0.02) and cd == pytest.approx(-0.75, abs=0.02)
    assert 0.44 <= le <= 0.52 and 0.44 <= ld <= 0.52 and ke > 0.8 and kd > 0.8


def test_perfil_sem_fileira_nao_preenche():
    t = np.round(np.arange(-1.5, 1.5, 0.03), 4)
    (ce, le, ke), (cd, ld, kd) = localizar_centros(PerfilTransversal(t, np.zeros_like(t)), CFG)
    assert (ce, le, ke, cd, ld, kd) == (None, None, 0.0, None, None, 0.0)
    (ce, _, _), _ = localizar_centros(PerfilTransversal(t, np.full_like(t, np.nan)), CFG)
    assert ce is None


def test_fileira_fora_da_semijanela_e_ignorada():
    t = np.round(np.arange(-1.5, 1.5, 0.03), 4)
    v = np.zeros_like(t)
    v[(t >= 1.55 - 0.24) & (t <= 1.55 + 0.24)] = 1.0  # +0,80 da posição projetada: fora de ±0,50
    (ce, _, _), _ = localizar_centros(PerfilTransversal(t, v), CFG)
    assert ce is None


def test_detecta_fileiras_com_deriva_constante(ambiente):
    _, dados, fb = ambiente
    p3 = dados.passadas[3]
    dets = detectar_passada(p3, fb, CFG)
    assert len(dets) == 9
    for d in dets:
        assert d.t_esq_m == pytest.approx(0.75 + 0.30, abs=0.03)
        assert d.t_dir_m == pytest.approx(-0.75 + 0.30, abs=0.03)
        assert 0.42 <= d.largura_esq_m <= 0.54 and 0.42 <= d.largura_dir_m <= 0.54
        assert d.confianca_esq > 0.8 and d.confianca_dir > 0.8
        assert d.normal_esq == pytest.approx((0.0, 1.0))


def test_falha_na_estacao_e_trecho_sem_fileira(ambiente):
    _, dados, fb = ambiente
    # P2: lacuna na fileira esquerda cobrindo a estação x = 30 (índice 2)
    d2 = detectar_passada(dados.passadas[2], fb, CFG)
    assert d2[2].t_esq_m is None and d2[2].t_dir_m == pytest.approx(-0.45, abs=0.03)
    assert d2[1].t_esq_m is not None and d2[3].t_esq_m is not None
    # P4: trecho sem fileira entre x = 45 e 65 (estações 50 e 60, índices 4 e 5)
    d4 = detectar_passada(dados.passadas[4], fb, CFG)
    for i in (4, 5):
        assert d4[i].t_esq_m is None and d4[i].t_dir_m is None
    assert d4[3].t_esq_m is not None and d4[6].t_dir_m is not None


def test_estacao_fora_do_raster_devolve_vazio(ambiente):
    _, _, fb = ambiente
    perfil = amostrar_perfil(fb, syn.ORIGEM_X + 500, syn.ORIGEM_Y + 10, (0.0, 1.0), (1.0, 0.0), CFG)
    assert np.isnan(perfil.valores).all()
