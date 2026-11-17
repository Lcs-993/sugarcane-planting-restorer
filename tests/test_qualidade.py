"""Testes do módulo qualidade.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
from dataclasses import replace

import pytest

import sinteticos as syn
from linhas_plantio.config import Config
from linhas_plantio.desvio import calcular_desvios
from linhas_plantio.deteccao import detectar_passada
from linhas_plantio.qualidade import avaliar_geometria, avaliar_passada, calcular_confianca, marcar_saltos
from linhas_plantio.tipos import EstacaoDesvio

CFG = Config()


def est(desvio=0.0, esp=1.50, le=0.48, ld=0.48, status="detectado", conf=0.9, s=0.0):
    return EstacaoDesvio("P0", "T1", s, 0.0, 0.0, (0.0, 1.0), desvio, esp, le, ld, status, conf)


def test_espacamento_gemeas_fora_da_tolerancia_gera_duvidoso():
    assert avaliar_geometria(est(esp=1.50), CFG).status == "detectado"
    assert avaliar_geometria(est(esp=1.62), CFG).status == "detectado"  # dentro de ±0,15
    assert avaliar_geometria(est(esp=1.80), CFG).status == "duvidoso"
    assert avaliar_geometria(est(esp=1.20), CFG).status == "duvidoso"


def test_largura_fora_da_tolerancia_gera_duvidoso():
    assert avaliar_geometria(est(le=0.55), CFG).status == "detectado"  # 0,50 + 0,10 = 0,60
    assert avaliar_geometria(est(le=0.75), CFG).status == "duvidoso"
    assert avaliar_geometria(est(ld=0.20), CFG).status == "duvidoso"


def test_geometria_nao_altera_duvidosa_nem_sem_valor():
    e = est(desvio=None, esp=None, le=None, ld=None, status="duvidoso", conf=0.0)
    assert avaliar_geometria(e, CFG) == e


def test_salto_isolado_e_marcado_sem_contaminar_vizinhos():
    d = [0.30, 0.31, 0.29, 1.20, 0.30, 0.32, 0.31]
    out = marcar_saltos([est(desvio=v, s=10.0 * i) for i, v in enumerate(d)], CFG)
    assert [e.status for e in out] == ["detectado"] * 3 + ["duvidoso"] + ["detectado"] * 3


def test_deriva_suave_nao_e_marcada():
    d = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]  # 0,10 m a cada estação
    assert all(e.status == "detectado" for e in marcar_saltos([est(desvio=v) for v in d], CFG))


def test_confianca_entre_zero_e_um_e_ordenada():
    perfeita = calcular_confianca(est(conf=1.0), CFG)
    borda = calcular_confianca(est(esp=1.64, conf=1.0), CFG)
    estimada = calcular_confianca(est(status="estimado", esp=None, conf=1.0), CFG)
    duvidosa = calcular_confianca(est(status="duvidoso", conf=1.0), CFG)
    semvalor = calcular_confianca(est(desvio=None, status="duvidoso", conf=0.0), CFG)
    assert perfeita == pytest.approx(1.0)
    assert 0 < borda < perfeita and estimada < perfeita and duvidosa <= 0.3 and semvalor == 0.0
    assert all(0.0 <= v <= 1.0 for v in (perfeita, borda, estimada, duvidosa, semvalor))


def test_avaliar_passada_encadeia():
    ests = [est(desvio=0.3, s=0.0), est(desvio=0.3, esp=1.9, s=10.0), est(desvio=0.3, s=20.0)]
    out = avaliar_passada(ests, CFG)
    assert [e.status for e in out] == ["detectado", "duvidoso", "detectado"]
    assert out[1].confianca <= 0.3 < out[0].confianca


def test_sintetico_espacamento_fora_da_tolerancia_gera_duvidoso(tmp_path):
    """Fileira direita da P3 deslocada 0,40 m: espaçamento de 1,90 m entre gêmeas."""
    caso = syn.gerar_caso(tmp_path, syn.deriva_constante(0.0), lacunas=[], ajustes_dir_m={3: -0.40})
    dados, fonte, fb = syn.preparar(caso, CFG)
    try:
        def rodar(i):
            p = dados.passadas[i]
            return avaliar_passada(calcular_desvios(p, detectar_passada(p, fb, CFG), CFG), CFG)

        anomala, normal = rodar(3), rodar(2)
    finally:
        fonte.fechar()
    assert all(e.status == "duvidoso" for e in anomala)
    assert all(e.espacamento_gemeas_m == pytest.approx(1.90, abs=0.04) for e in anomala)
    assert all(e.status == "detectado" for e in normal)
