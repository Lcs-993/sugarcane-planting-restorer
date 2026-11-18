import pytest

from deteccao_linhas.config import Config
from deteccao_linhas.qualidade import calcular_confianca, classificar_ponto
from deteccao_linhas.tipos import PosicaoFileira


def _pos(**kw):
    base = dict(id_bloco="B", t_m=0.0, x=0.0, y=0.0, largura_m=0.48, proeminencia=0.6, coerencia=1.0,
                ajuste_pente=1.0, espacamento_vizinha_m=1.5, salto=False, confianca=0.0)
    base.update(kw)
    return PosicaoFileira(**base)


def test_confianca_maxima_e_componentes():
    cfg = Config()
    assert calcular_confianca(_pos(), cfg) == pytest.approx(1.0)
    assert calcular_confianca(_pos(largura_m=None), cfg) == pytest.approx(0.8)
    assert calcular_confianca(_pos(largura_m=0.60), cfg) == pytest.approx(0.8 + 0.2 * (1 - 0.10 / 0.15))
    assert calcular_confianca(_pos(coerencia=0.0), cfg) == pytest.approx(0.7)
    assert calcular_confianca(_pos(proeminencia=0.05), cfg) == pytest.approx(0.7)
    assert calcular_confianca(_pos(ajuste_pente=0.0), cfg) == pytest.approx(0.8)


def test_classificar():
    cfg = Config()
    assert classificar_ponto(0.49, cfg) == "duvidoso"
    assert classificar_ponto(0.50, cfg) == "detectado"
