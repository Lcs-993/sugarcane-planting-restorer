"""Teste de ponta a ponta com dados sintéticos: três perfis de deriva conhecidos, falhas de planta
e um trecho sem fileira detectável.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
Os erros impressos abaixo são contra a deriva sintética conhecida, não contra medição de campo.
"""
import geopandas as gpd
import numpy as np
import pytest

import sinteticos as syn
from linhas_plantio.cli import executar_correcao
from linhas_plantio.config import Config

CASOS = {
    "constante": syn.deriva_constante(0.30),
    "rotacao_linear": syn.deriva_rotacao(-0.30, 0.30),
    "senoidal": syn.deriva_senoidal(0.20, 60.0),
}


@pytest.fixture(scope="module", params=list(CASOS))
def rodada(request, tmp_path_factory):
    nome = request.param
    pasta = tmp_path_factory.mktemp(nome)
    caso = syn.gerar_caso(pasta, CASOS[nome])
    saida = pasta / "saida.gpkg"
    resultados = executar_correcao(caso.raster, caso.talhoes, caso.linhas, saida, Config())
    return nome, caso, saida, resultados


def _erros(resultados, deriva):
    corr, proj = [], []
    for i, r in enumerate(resultados):
        c, p = syn.erros_laterais(r.linha_corrigida, i, deriva)
        corr.append(c)
        proj.append(p)
    return corr, proj


def test_linha_corrigida_nao_fica_pior_que_a_projetada(rodada):
    nome, caso, _, resultados = rodada
    corr, proj = _erros(resultados, caso.deriva)
    todos_c, todos_p = np.concatenate(corr), np.concatenate(proj)
    print(
        f"\n[sintético:{nome}] erro lateral (m) vs deriva conhecida | "
        f"corrigida: médio={todos_c.mean():.3f} máx={todos_c.max():.3f} | "
        f"projetada sem correção: médio={todos_p.mean():.3f} máx={todos_p.max():.3f}"
    )
    for i, (c, p) in enumerate(zip(corr, proj)):
        assert c.mean() <= p.mean(), f"{nome}: passada P{i} piorou (corrigida {c.mean():.3f} > projetada {p.mean():.3f})"
        assert c.max() <= p.max(), f"{nome}: passada P{i} piorou no máximo"


def test_estacao_sem_fileira_nunca_e_preenchida_em_silencio(rodada):
    _, _, _, resultados = rodada
    p4 = resultados[4].estacoes  # trecho sem fileira entre x = 45 e 65 (estações 50 e 60)
    for i in (4, 5):
        assert p4[i].status in ("duvidoso", "interpolado")
    # bracketed por estações boas (x = 40 e 70): interpolado, com confiança baixa
    assert [p4[i].status for i in (4, 5)] == ["interpolado", "interpolado"]
    assert all(p4[i].confianca <= 0.3 for i in (4, 5))
    assert resultados[4].frac_interpolada == pytest.approx(2 / 9)


def test_falha_de_planta_na_estacao_vira_estimada(rodada):
    _, _, _, resultados = rodada
    assert resultados[2].estacoes[2].status == "estimado"  # fileira esquerda ausente em x = 30
    assert sum(e.status == "detectado" for e in resultados[1].estacoes) == 9  # falha entre estações não atrapalha


def test_saida_gpkg_tem_as_duas_camadas(rodada):
    _, _, saida, _ = rodada
    lin = gpd.read_file(saida, layer="linhas_corrigidas")
    est = gpd.read_file(saida, layer="estacoes")
    assert len(lin) == 7 and len(est) == 63
    assert set(est["status"]) <= {"detectado", "estimado", "interpolado", "duvidoso"}
    assert est["confianca"].between(0, 1).all()
    assert lin.crs.to_epsg() == 31983 and est.crs.to_epsg() == 31983


def test_sinal_do_desvio_acompanha_a_deriva(rodada):
    nome, caso, _, resultados = rodada
    for i, r in enumerate(resultados):
        for e in r.estacoes:
            if e.status == "detectado":
                esperado = float(caso.deriva(np.array([e.x - syn.ORIGEM_X]))[0])
                assert e.desvio_m == pytest.approx(esperado, abs=0.10), f"{nome} P{i} s={e.estacao_m}"
