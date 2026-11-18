import math

import numpy as np
import pytest
from shapely.geometry import box

from deteccao_linhas.config import Config
from deteccao_linhas.indice_binarizacao import (abrir_fonte_binaria, abrir_fonte_indice, calcular_limiar_otsu,
                                                recortar_talhao)
from deteccao_linhas.perfil_lateral import calcular_perfil, gerar_blocos
from deteccao_linhas.tipos import DirecaoFileiras, ErroContrato, Regiao, Talhao

from conftest import gerar_fileiras


def _reg(poli, az=0.0, i="R1"):
    a = math.radians(az)
    return Regiao(i, "T", poli, DirecaoFileiras(az, (math.sin(a), math.cos(a)), 1.0, False))


def test_blocos_cobrem_sem_sobrepor():
    cfg = Config()
    reg = _reg(box(0, 0, 40, 100))
    blocos = gerar_blocos([reg], (0.0, 1.0), (20.0, 50.0), cfg)
    assert len(blocos) == 10
    assert [b.s_global_m for b in blocos] == sorted(b.s_global_m for b in blocos)
    assert sum(b.poligono.area for b in blocos) == pytest.approx(40 * 100, rel=1e-6)
    for a, b in zip(blocos, blocos[1:]):
        assert a.poligono.intersection(b.poligono).area < 1e-6
    assert blocos[0].comprimento_m == pytest.approx(10.0)
    assert blocos[0].t_max_m - blocos[0].t_min_m == pytest.approx(40.0)
    assert blocos[0].n == (-1.0, 0.0)


def test_blocos_regiao_girada_e_sem_direcao():
    cfg = Config()
    blocos = gerar_blocos([_reg(box(0, 0, 60, 60), az=30.0)], (math.sin(math.radians(30)), math.cos(math.radians(30))),
                          (30, 30), cfg)
    total = sum(b.poligono.area for b in blocos)
    assert blocos and 0.99 * 3600 <= total <= 3600 + 1e-6  # cantos < 2 m de comprimento são descartados
    with pytest.raises(ErroContrato):
        gerar_blocos([Regiao("R", "T", box(0, 0, 10, 10), None)], (0, 1), (0, 0), cfg)


def _fonte(tmp_path, **kw):
    tif = gerar_fileiras(tmp_path / "o.tif", **kw)
    cfg = Config()
    f = abrir_fonte_indice(tif, cfg)
    area = recortar_talhao(Talhao("T1", box(394000, 7775000 - kw.get("altura_m", 60.0),
                                            394000 + kw.get("largura_m", 60.0), 7775000)), cfg)
    return f, abrir_fonte_binaria(f, area, calcular_limiar_otsu(f, area, cfg), cfg), area, cfg


def test_perfil_picos_espacados(tmp_path):
    f, fb, area, cfg = _fonte(tmp_path)
    try:
        reg = _reg(area.poligono_util)
        b = gerar_blocos([reg], (0.0, 1.0), (394030, 7774970), cfg)[0]
        p = calcular_perfil(fb, b, cfg)
        assert p.cobertura > 0.99
        assert np.nanmax(p.vegetacao) > 0.95 and np.nanmin(p.vegetacao) < 0.05
        centros = p.t_m[(p.vegetacao > 0.5)]
        # agrupa bins contíguos em picos
        grupos = np.split(centros, np.where(np.diff(centros) > 0.2)[0] + 1)
        meios = np.array([g.mean() for g in grupos if len(g) > 3])
        assert np.allclose(np.diff(meios), 1.5, atol=0.07)
        larg = [g[-1] - g[0] + 0.06 for g in grupos if len(g) > 3]
        assert np.allclose(larg, 0.48, atol=0.12)
        # coerência alta nas fileiras, baixa fora
        assert np.nanmean(p.coerencia[p.vegetacao > 0.5]) > 0.95
        assert np.nanmean(p.coerencia[p.vegetacao < 0.05]) < 0.05
    finally:
        f.fechar()


def test_perfil_com_falha_reduz_coerencia_mas_mantem_pico(tmp_path):
    # falha de 6 m (de 20 m de bloco) numa fileira: vegetação cai, coerência cai
    f, fb, area, cfg = _fonte(tmp_path, falha=(10, 16, 6.0, 6.7), fase_m=0.3)
    try:
        b = gerar_blocos([_reg(area.poligono_util)], (0.0, 1.0), (394030, 7774970), Config(comprimento_bloco_m=20, passo_bloco_m=20))[0]
        p = calcular_perfil(fb, b, Config(comprimento_bloco_m=20, passo_bloco_m=20))
        assert np.nanmax(p.vegetacao) > 0.95
        assert 0.4 < np.nanmin(p.vegetacao[p.vegetacao > 0.5]) < 0.9
    finally:
        f.fechar()


def test_perfil_fora_do_raster_devolve_vazio(tmp_path):
    f, fb, area, cfg = _fonte(tmp_path, largura_m=20, altura_m=20)
    try:
        reg = _reg(box(400000, 7000000, 400020, 7000040))
        b = gerar_blocos([reg], (0, 1), (0, 0), cfg)[0]
        p = calcular_perfil(fb, b, cfg)
        assert p.cobertura == 0.0 and np.isnan(p.vegetacao).all()
    finally:
        f.fechar()
