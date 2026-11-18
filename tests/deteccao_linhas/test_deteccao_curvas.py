"""Fileiras em curva (modo_blocos="faixas"), com imagens SINTÉTICAS de verdade exata.

AVISO: testes sintéticos mostram que o algoritmo funciona sobre imagem simulada, não a acurácia em campo
(que só sai da validação com RTK, docs/plano-validacao.md). Os limiares abaixo são metas do algoritmo
sobre arcos concêntricos e uma curva em S, não garantias sobre talhões reais.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from shapely.ops import unary_union

import diagnostico_curvas as dg  # gerador e métricas do diagnóstico (mesma pasta de testes)
from deteccao_linhas.config import Config, ErroConfig, carregar_config
from deteccao_linhas.orientacao import CampoDirecao, estimar_campo_direcao
from deteccao_linhas.perfil_lateral import gerar_blocos_faixas
from deteccao_linhas.qualidade import marcar_saltos_curvos
from deteccao_linhas.tipos import PontoFileira, Trilha

CFG = Config()  # padrões: modo_blocos="faixas"


@pytest.fixture(scope="module")
def pasta(tmp_path_factory):
    return tmp_path_factory.mktemp("curvas")


def _rodar(pasta, nome, raio, cfg, s_forma=False):
    cen = dg.montar_cenario(pasta, nome, raio, s_forma=s_forma, realista=True)
    return dg.rodar(cen, cfg, pasta, "t")


@pytest.mark.parametrize("raio", [None, 400, 100, 50])
def test_deteccao_curvas_arcos_cobertura_e_erro(pasta, raio):
    r = _rodar(pasta, f"a{raio}", raio, CFG)
    assert "erro" not in r
    assert r["cobertura_30cm"] >= 0.80
    assert r["conf_gt25"] <= 0.02  # erro > 25 cm entre os pontos 'detectado'
    assert r["n_fileiras_detectadas"] <= 1.2 * r["n_fileiras_verdade_ge30m"]  # sem fragmentação forte
    assert r["fileiras_com_troca"] <= 1  # no R=50 uma trilha cruza para a fileira vizinha (ver docs/diagnostico-curvas.md)


def test_deteccao_curvas_em_s(pasta):
    r = _rodar(pasta, "s100", 100, CFG, s_forma=True)
    assert r["cobertura_30cm"] >= 0.80
    assert r["conf_gt25"] <= 0.02
    assert r["n_fileiras_detectadas"] <= 1.2 * r["n_fileiras_verdade_ge30m"]


def test_modo_regiao_reproduz_o_comportamento_antigo(pasta):
    """Com modo_blocos="regiao" a falha em curva documentada continua reproduzível (comparação antes x depois)."""
    r = _rodar(pasta, "antigo100", 100, replace(CFG, modo_blocos="regiao"))
    assert r["cobertura_30cm"] < 0.5
    reta = _rodar(pasta, "antigoreta", None, replace(CFG, modo_blocos="regiao"))
    assert reta["cobertura_30cm"] >= 0.90 and reta["n_fileiras_detectadas"] == 20


def test_campo_de_direcao_segue_o_arco(pasta):
    from deteccao_linhas.entrada import carregar_entrada
    from deteccao_linhas.indice_binarizacao import (abrir_fonte_binaria, abrir_fonte_indice,
                                                    calcular_limiar_otsu, recortar_talhao)
    cen = dg.montar_cenario(pasta, "campo100", 100, realista=True)
    dados = carregar_entrada(cen["tif"], cen["talhao"], CFG)
    fonte = abrir_fonte_indice(dados.caminho_ortomosaico, CFG)
    try:
        area = recortar_talhao(dados.talhoes[0], CFG)
        fb = abrir_fonte_binaria(fonte, area, calcular_limiar_otsu(fonte, area, CFG), CFG)
        campo, janelas, u_ref = estimar_campo_direcao(fb, area, CFG)
    finally:
        fonte.fechar()
    assert isinstance(campo, CampoDirecao)
    erros = [abs(dg._dif180(j.direcao.azimute_graus, dg._azimute_verdade(cen["curva"], *j.poligono.centroid.coords[0])))
             for j in janelas]
    assert np.median(erros) < 1.5 and max(erros) < 5.0
    assert abs(np.hypot(*u_ref) - 1.0) < 1e-9
    # blocos ao longo das linhas de corrente: núcleos sem sobreposição relevante e todos dentro da área útil
    blocos = gerar_blocos_faixas(campo, area.poligono_util, u_ref, area.poligono_util.centroid.coords[0], CFG)
    assert blocos
    util = area.poligono_util.buffer(0.01)
    assert all(b.nucleo is not None and util.contains(b.nucleo.buffer(-0.01)) for b in blocos)
    por_faixa: dict[str, list] = {}
    for b in blocos:
        por_faixa.setdefault(b.id_regiao, []).append(b.nucleo)
    faixas = list(por_faixa)
    for i, fa in enumerate(faixas):
        for fb_ in faixas[i + 1:]:
            ua = unary_union(por_faixa[fa])
            ub = unary_union(por_faixa[fb_])
            assert ua.intersection(ub).area < 0.02 * min(ua.area, ub.area)


def _trilha(xy, status="detectado"):
    pts = tuple(PontoFileira(id_bloco=f"B{i}", x=float(x), y=float(y), posicao_m=0.0, status=status, confianca=0.9)
                for i, (x, y) in enumerate(xy))
    return Trilha(pontos=pts)


def _arco(raio, n=15, passo=10.0):
    a = np.arange(n) * passo / raio
    return np.column_stack([raio * np.sin(a), raio * (1 - np.cos(a))])


def test_marcar_saltos_curvos_nao_marca_arco_regular_mas_marca_salto():
    t = marcar_saltos_curvos(_trilha(_arco(100.0)), replace(CFG, curvatura_duvidosa_1_m=0.0))
    assert all(p.status == "detectado" for p in t.pontos)  # a curvatura sozinha não é erro lateral
    xy = _arco(100.0)
    xy[7] += np.array([0.0, 0.8])  # um ponto 80 cm fora do arco
    t = marcar_saltos_curvos(_trilha(xy), replace(CFG, curvatura_duvidosa_1_m=0.0))
    assert [i for i, p in enumerate(t.pontos) if p.status == "duvidoso"] == [7]


def test_curvatura_muito_alta_vira_duvidosa_e_posicao_nao_muda():
    xy = _arco(15.0, n=12, passo=5.0)
    t = marcar_saltos_curvos(_trilha(xy), replace(CFG, curvatura_duvidosa_1_m=0.04))
    assert any(p.status == "duvidoso" for p in t.pontos)
    assert [(p.x, p.y) for p in t.pontos] == [tuple(map(float, q)) for q in xy]
    t2 = marcar_saltos_curvos(_trilha(xy), replace(CFG, curvatura_duvidosa_1_m=0.0))
    assert all(p.status == "detectado" for p in t2.pontos)


def test_config_novos_parametros(tmp_path):
    assert CFG.modo_blocos == "faixas" and CFG.passo_efetivo_m == 5.0 and CFG.max_falhas_efetivas == 6
    assert replace(CFG, modo_blocos="regiao").passo_efetivo_m == CFG.passo_bloco_m
    with pytest.raises(ErroConfig):
        Config(modo_blocos="curvo")
    with pytest.raises(ErroConfig):
        Config(janela_direcao_m=0.0)
    y = tmp_path / "c.yaml"
    y.write_text("modo_blocos: regiao\njanela_direcao_m: 10\n", encoding="utf-8")
    c = carregar_config(y)
    assert c.modo_blocos == "regiao" and c.janela_direcao_m == 10.0
