import numpy as np
import pytest
from shapely.geometry import box

from deteccao_linhas.config import Config
from deteccao_linhas.indice_binarizacao import (abrir_fonte_binaria, abrir_fonte_indice, calcular_indice,
                                                calcular_limiar_otsu, recortar_talhao)
from deteccao_linhas.tipos import ErroConfig, ErroContrato, ErroDeteccao, Talhao

from conftest import gerar_fileiras


def test_exg_normalizado_puro():
    b = np.zeros((3, 1, 3), dtype=np.uint8)
    b[:, 0, 0] = (60, 160, 50)  # vegetação
    b[:, 0, 1] = (150, 110, 80)  # solo
    b[:, 0, 2] = (0, 0, 0)  # soma zero
    v = calcular_indice(b, Config())
    assert v.dtype == np.float32
    assert v[0, 0] > 0.3 > v[0, 1]
    assert np.isnan(v[0, 2])


def test_exg_bruto_e_vari():
    b = np.array([60, 160, 50], dtype=np.uint8).reshape(3, 1, 1)
    assert calcular_indice(b, Config(variante_exg="bruto"))[0, 0] == pytest.approx(2 * 160 - 60 - 50)
    assert calcular_indice(b, Config(indice="vari"))[0, 0] == pytest.approx((160 - 60) / (160 + 60 - 50))


def test_ler_janela_resolucao_e_media(ortho_simples):
    tif, _ = ortho_simples
    f = abrir_fonte_indice(tif, Config())
    try:
        j = f.ler_janela((394000, 7774990, 394010, 7775000))
        assert j.valores.shape == (167, 167) or abs(j.valores.shape[0] - 10 / 0.06) <= 1
        assert j.validade.all()
        assert abs(j.transform.a - 0.06) < 0.001
        with pytest.raises(ErroConfig):
            f.ler_janela((394000, 7774990, 394010, 7775000), 0.001)
        with pytest.raises(ErroContrato):
            f.ler_janela((0, 0, 10, 10))
    finally:
        f.fechar()


def test_recortar_talhao():
    t = Talhao("a", box(0, 0, 100, 100))
    a = recortar_talhao(t, Config(buffer_interno_m=5))
    assert a.bounds == (5, 5, 95, 95)
    with pytest.raises(ErroContrato):
        recortar_talhao(Talhao("b", box(0, 0, 8, 8)), Config(buffer_interno_m=5))


def test_otsu_e_binario(ortho_simples):
    tif, _ = ortho_simples
    cfg = Config()
    f = abrir_fonte_indice(tif, cfg)
    try:
        t = Talhao("T1", box(394000, 7774940, 394060, 7775000))
        area = recortar_talhao(t, cfg)
        lim = calcular_limiar_otsu(f, area, cfg)
        # índice solo ~0,05..; vegetação ~0,35: limiar entre os dois
        solo = calcular_indice(np.array([150, 110, 80], dtype=np.uint8).reshape(3, 1, 1), cfg)[0, 0]
        veg = calcular_indice(np.array([60, 160, 50], dtype=np.uint8).reshape(3, 1, 1), cfg)[0, 0]
        assert solo < lim <= veg
        fb = abrir_fonte_binaria(f, area, lim, cfg)
        j = fb.ler_janela(area.bounds)
        assert j.valores.dtype == bool
        frac = j.valores[j.validade].mean()
        assert frac == pytest.approx(0.48 / 1.5, abs=0.04)
        # fora da área útil (borda de 5 m) fica inválido ao ler o talhão inteiro
        j2 = fb.ler_janela((394000, 7774940, 394060, 7775000))
        assert not j2.validade[0, 0] and j2.validade[j2.validade.shape[0] // 2, j2.validade.shape[1] // 2]
    finally:
        f.fechar()


def test_otsu_sem_pixels(tmp_path):
    tif = gerar_fileiras(tmp_path / "o.tif", largura_m=20, altura_m=20)
    cfg = Config()
    f = abrir_fonte_indice(tif, cfg)
    try:
        # talhão longe do raster, mas com bounds intersectando nada
        area = recortar_talhao(Talhao("x", box(500000, 7000000, 500100, 7000100)), cfg)
        with pytest.raises(ErroDeteccao):
            calcular_limiar_otsu(f, area, cfg)
    finally:
        f.fechar()
