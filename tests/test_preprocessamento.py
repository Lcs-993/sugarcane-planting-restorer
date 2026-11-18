"""Testes do módulo preprocessamento.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import sinteticos as syn
from linhas_plantio.config import Config
from linhas_plantio.preprocessamento import abrir_fonte_indice, calcular_indice, recortar_talhao
from linhas_plantio.tipos import ErroContrato, Talhao


@pytest.fixture(scope="module")
def caso(tmp_path_factory):
    return syn.gerar_caso(tmp_path_factory.mktemp("pre"), syn.deriva_constante(), lacunas=[])


def _px(r, g, b):
    return np.array([[[r]], [[g]], [[b]]], dtype=np.float32)


def test_exg_solo_e_cana():
    cfg = Config()
    assert calcular_indice(_px(150, 115, 85), cfg)[0, 0] == pytest.approx((2 * 115 - 150 - 85) / 350, abs=1e-5)
    assert calcular_indice(_px(55, 130, 45), cfg)[0, 0] == pytest.approx((2 * 130 - 55 - 45) / 230, abs=1e-5)


def test_vari_ndvi_e_divisao_por_zero():
    assert calcular_indice(_px(150, 115, 85), Config(indice="vari"))[0, 0] == pytest.approx((115 - 150) / (115 + 150 - 85), abs=1e-5)
    nir = np.array([[[200]], [[100]], [[100]], [[100]]], dtype=np.float32)[[1, 2, 3, 0]]  # R=100,G=100,B=100,NIR=200
    assert calcular_indice(nir, Config(indice="ndvi", banda_nir=4))[0, 0] == pytest.approx((200 - 100) / (200 + 100), abs=1e-5)
    assert np.isnan(calcular_indice(_px(0, 0, 0), Config())[0, 0])


def test_ler_janela_por_bounds(caso):
    cfg = Config()
    with abrir_fonte_indice(caso.raster, cfg) as fonte:
        assert fonte.resolucao_m == pytest.approx(0.03)
        x, y = syn.ORIGEM_X + 50, syn.ORIGEM_Y + 18
        jan = fonte.ler_janela((x, y, x + 3.0, y + 3.0))
        assert jan.valores.dtype == np.float32
        assert 99 <= jan.valores.shape[1] <= 102
        assert jan.validade.all()
        assert abs(jan.transform.c - x) <= 0.03  # janela arredondada na grade do raster
        # linha P3 (eixo y=19) com deriva constante 0,30: fileira esquerda em y = 20,05
        assert np.nanmax(jan.valores) > 0.5 and np.nanmin(jan.valores) < 0.1


def test_janela_fora_do_raster(caso):
    with abrir_fonte_indice(caso.raster, Config()) as fonte:
        with pytest.raises(ErroContrato, match="não intersecta"):
            fonte.ler_janela((syn.ORIGEM_X + 500, syn.ORIGEM_Y, syn.ORIGEM_X + 510, syn.ORIGEM_Y + 10))


def test_nodata_vira_sem_validade(tmp_path):
    caminho = tmp_path / "nd.tif"
    img = np.full((3, 40, 40), 120, dtype=np.uint8)
    img[:, :, :20] = 0
    with rasterio.open(caminho, "w", driver="GTiff", height=40, width=40, count=3, dtype="uint8",
                       crs=syn.CRS_SINTETICO, transform=from_origin(0, 40, 1, 1), nodata=0) as ds:
        ds.write(img)
    with abrir_fonte_indice(caminho, Config()) as fonte:
        jan = fonte.ler_janela((0, 0, 40, 40))
    assert not jan.validade[:, :20].any() and jan.validade[:, 20:].all()
    assert np.isnan(jan.valores[:, :20]).all()


def test_banda_inexistente(caso):
    with pytest.raises(ErroContrato, match="inexistente"):
        abrir_fonte_indice(caso.raster, Config(indice="ndvi", banda_nir=4))


def test_recortar_talhao_com_buffer():
    t = Talhao("A", box(0, 0, 100, 36))
    area = recortar_talhao(t, Config(buffer_interno_m=5.0))
    assert area.bounds == (5.0, 5.0, 95.0, 31.0)
    with pytest.raises(ErroContrato, match="esvazia"):
        recortar_talhao(Talhao("B", box(0, 0, 8, 8)), Config(buffer_interno_m=5.0))
