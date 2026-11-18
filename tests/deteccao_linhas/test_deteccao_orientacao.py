import math

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from deteccao_linhas.config import Config
from deteccao_linhas.indice_binarizacao import (abrir_fonte_binaria, abrir_fonte_indice, calcular_limiar_otsu,
                                                recortar_talhao)
from deteccao_linhas.orientacao import (_dif180, dividir_em_regioes, estimar_direcao_regiao, estimar_direcoes)
from deteccao_linhas.tipos import ErroContrato, ErroDeteccao, JanelaRaster, Regiao, Talhao

from conftest import gerar_fileiras


class FonteFalsa:
    """FonteBinaria sintética: azimute (graus) das fileiras em função de x; None => solo puro."""

    def __init__(self, azimute_de_x, esp=1.5, faixa=0.48):
        self.f, self.esp, self.faixa = azimute_de_x, esp, faixa

    def ler_janela(self, bounds, resolucao_m=None):
        res = resolucao_m or 0.06
        x0, y0, x1, y1 = bounds
        w, h = int(round((x1 - x0) / res)), int(round((y1 - y0) / res))
        X = x0 + (np.arange(w) + 0.5) * res
        Y = y1 - (np.arange(h) + 0.5) * res
        XX, YY = np.meshgrid(X, Y)
        az = np.vectorize(lambda v: np.nan if self.f(v) is None else self.f(v))(XX)
        a = np.radians(np.nan_to_num(az))
        t = (XX - x0) * np.cos(a) - (YY - y0) * np.sin(a)
        d = np.abs(((t - 0.3 + self.esp / 2) % self.esp) - self.esp / 2)
        veg = (d <= self.faixa / 2) & ~np.isnan(az)
        return JanelaRaster(veg, np.ones_like(veg), from_origin(x0, y1, (x1 - x0) / w, (y1 - y0) / h))


def _regiao(b, i="R"):
    return Regiao(i, "T", box(*b), None)


@pytest.mark.parametrize("az", [0.0, 20.0, 95.0, 160.0])
def test_direcao_regiao_recupera_angulo(az):
    cfg = Config()
    fb = FonteFalsa(lambda x: az)
    d = estimar_direcao_regiao(fb, _regiao((0, 0, 60, 60)), cfg)
    assert abs(_dif180(d.azimute_graus, az)) < 0.6
    assert d.confianca > 0.5 and not d.herdada
    assert d.vetor[1] >= 0  # sentido provisório com norte positivo
    assert math.isclose(math.hypot(*d.vetor), 1.0)


def test_pipeline_real_sintetico(tmp_path):
    tif = gerar_fileiras(tmp_path / "o.tif", largura_m=80, altura_m=80, angulo_graus=12.0)
    cfg = Config(regiao_m=50.0, area_minima_regiao_m2=500.0)
    f = abrir_fonte_indice(tif, cfg)
    try:
        area = recortar_talhao(Talhao("T1", box(394000, 7774920, 394080, 7775000)), cfg)
        fb = abrir_fonte_binaria(f, area, calcular_limiar_otsu(f, area, cfg), cfg)
        regs = dividir_em_regioes(area, cfg)
        assert len(regs) >= 2 and all(r.direcao is None for r in regs)
        out, u_ref = estimar_direcoes(fb, regs, cfg)
        for r in out:
            assert abs(_dif180(r.direcao.azimute_graus, 12.0)) < 1.0
        assert abs(u_ref[0] - math.sin(math.radians(12))) < 0.02
    finally:
        f.fechar()


def test_regiao_sem_contraste_levanta():
    with pytest.raises(ErroDeteccao):
        estimar_direcao_regiao(FonteFalsa(lambda x: None), _regiao((0, 0, 60, 60)), Config())


def test_regiao_herda_direcao_marcada():
    cfg = Config(area_minima_regiao_m2=500.0)
    # esquerda e meio com 10°, direita sem vegetação (sem contraste)
    fb = FonteFalsa(lambda x: 10.0 if x < 120 else None)
    regs = [_regiao((0, 0, 60, 60), "A"), _regiao((60, 0, 120, 60), "B"), _regiao((120, 0, 180, 60), "C")]
    out, u_ref = estimar_direcoes(fb, regs, cfg)
    por_id = {r.id_regiao: r.direcao for r in out}
    assert not por_id["A"].herdada and not por_id["B"].herdada
    assert por_id["C"].herdada and por_id["C"].confianca == 0.0
    assert abs(_dif180(por_id["C"].azimute_graus, 10.0)) < 1.0


def test_regiao_destoante_herda():
    cfg = Config(area_minima_regiao_m2=500.0, desvio_angular_max_graus=15.0)
    fb = FonteFalsa(lambda x: 10.0 if x < 120 else (10.0 if x < 180 else 60.0))
    regs = [_regiao((60 * i, 0, 60 * i + 60, 60), f"R{i}") for i in range(4)]
    out, _ = estimar_direcoes(fb, regs, cfg)
    assert [r.direcao.herdada for r in out] == [False, False, False, True]
    assert abs(_dif180(out[3].direcao.azimute_graus, 10.0)) < 1.0


def test_sentido_alinhado_a_u_ref_perto_de_180():
    cfg = Config(area_minima_regiao_m2=500.0)
    fb = FonteFalsa(lambda x: 179.5 if x < 60 else 0.5)
    regs = [_regiao((0, 0, 60, 60), "A"), _regiao((60, 0, 120, 60), "B")]
    out, u_ref = estimar_direcoes(fb, regs, cfg)
    for r in out:
        assert r.direcao.vetor[0] * u_ref[0] + r.direcao.vetor[1] * u_ref[1] > 0.99


def test_nenhuma_estimavel():
    with pytest.raises(ErroDeteccao):
        estimar_direcoes(FonteFalsa(lambda x: None), [_regiao((0, 0, 60, 60))], Config(area_minima_regiao_m2=500.0))


def test_dividir_sem_regiao():
    from deteccao_linhas.tipos import AreaTalhao
    area = AreaTalhao(Talhao("T", box(0, 0, 1, 1)), box(0, 0, 0, 0), (0, 0, 0, 0))
    with pytest.raises(ErroContrato):
        dividir_em_regioes(area, Config())
