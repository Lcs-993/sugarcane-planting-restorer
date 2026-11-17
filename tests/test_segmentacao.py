"""Testes do módulo segmentacao.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import numpy as np
import pytest
from skimage.filters import threshold_otsu

import sinteticos as syn
from linhas_plantio import segmentacao
from linhas_plantio.config import Config
from linhas_plantio.entrada import carregar_entrada
from linhas_plantio.preprocessamento import abrir_fonte_indice, recortar_talhao
from linhas_plantio.segmentacao import abrir_fonte_binaria, calcular_limiar_otsu
from linhas_plantio.tipos import ErroContrato


@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    caso = syn.gerar_caso(tmp_path_factory.mktemp("seg"), syn.deriva_constante(), lacunas=[])
    cfg = Config()
    dados = carregar_entrada(caso.raster, caso.talhoes, caso.linhas, cfg)
    fonte = abrir_fonte_indice(caso.raster, cfg)
    area = recortar_talhao(dados.talhoes[0], cfg)
    yield caso, cfg, fonte, area
    fonte.fechar()


def test_otsu_separa_solo_de_cana(ambiente):
    _, _, fonte, area = ambiente
    limiar = calcular_limiar_otsu(fonte, area)
    # índice ExG do solo sintético ~ -0,01 e da cana ~ 0,70
    assert 0.1 < limiar < 0.6


def test_otsu_por_blocos_igual_ao_calculo_em_memoria(ambiente, monkeypatch):
    _, _, fonte, area = ambiente
    jan = fonte.ler_janela(area.bounds)
    mask = jan.validade & segmentacao._mascara_poligono(area.poligono_util, jan.valores.shape, jan.transform)
    ref = threshold_otsu(jan.valores[mask], nbins=256)
    monkeypatch.setattr(segmentacao, "LADO_BLOCO_PX", 300)  # força muitos blocos
    por_blocos = calcular_limiar_otsu(fonte, area)
    passo = float(jan.valores[mask].max() - jan.valores[mask].min()) / 256
    assert por_blocos == pytest.approx(ref, abs=2 * passo)


def test_fonte_binaria_marca_fileira_e_fora_da_area(ambiente):
    _, _, fonte, area = ambiente
    fb = abrir_fonte_binaria(fonte, area, calcular_limiar_otsu(fonte, area))
    x, y = syn.ORIGEM_X + 50, syn.ORIGEM_Y + 19.75 + 0.30  # fileira esquerda de P3 com deriva 0,30
    jan = fb.ler_janela((x - 0.5, y - 0.1, x + 0.5, y + 0.1))
    assert jan.valores.dtype == bool and jan.valores.mean() > 0.9
    fora = fb.ler_janela((syn.ORIGEM_X + 1, syn.ORIGEM_Y + 10, syn.ORIGEM_X + 3, syn.ORIGEM_Y + 12))  # dentro do buffer interno
    assert not fora.validade.any() and not fora.valores.any()


def test_otsu_sem_pixels_validos(ambiente):
    caso, cfg, fonte, area = ambiente
    from dataclasses import replace
    from shapely.geometry import box
    area_fora = replace(area, poligono_util=box(syn.ORIGEM_X + 500, syn.ORIGEM_Y, syn.ORIGEM_X + 510, syn.ORIGEM_Y + 10),
                        bounds=(syn.ORIGEM_X + 500, syn.ORIGEM_Y, syn.ORIGEM_X + 510, syn.ORIGEM_Y + 10))
    with pytest.raises(ErroContrato, match="pixels válidos"):
        calcular_limiar_otsu(fonte, area_fora)
