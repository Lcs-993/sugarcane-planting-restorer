import pytest

from deteccao_linhas.config import Config
from deteccao_linhas.qualidade import avaliar_trilha, avaliar_trilhas, marcar_saltos_laterais
from deteccao_linhas.tipos import ErroContrato, PontoFileira, Trilha


def _trilha(xs, ys=None, status=None, conf=0.9):
    ys = ys or [10.0 * i for i in range(len(xs))]
    status = status or ["detectado"] * len(xs)
    return Trilha(tuple(PontoFileira(f"B{i}", x, y, 10.0 * i, s, conf)
                        for i, (x, y, s) in enumerate(zip(xs, ys, status))))


def test_salto_isolado_vira_duvidoso_sem_mover():
    t = _trilha([0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0])
    r = marcar_saltos_laterais(t, Config())
    assert [p.status for p in r.pontos] == ["detectado"] * 3 + ["duvidoso"] + ["detectado"] * 3
    assert [p.x for p in r.pontos] == [p.x for p in t.pontos]


def test_trilha_inclinada_reta_nao_marca():
    t = _trilha([0.1 * i for i in range(8)])  # inclinação constante
    assert all(p.status == "detectado" for p in marcar_saltos_laterais(t, Config()).pontos)


def test_variacao_abaixo_do_limite_nao_marca():
    t = _trilha([0.0, 0.0, 0.0, 0.2, 0.0, 0.0])
    assert all(p.status == "detectado" for p in marcar_saltos_laterais(t, Config()).pontos)


def test_interpolado_nao_e_alterado():
    t = _trilha([0.0, 0.0, 0.8, 0.0, 0.0], status=["detectado", "detectado", "interpolado", "detectado", "detectado"])
    r = marcar_saltos_laterais(t, Config())
    assert r.pontos[2].status == "interpolado"


def test_avaliar():
    t = _trilha([0.0, 0.0, 0.0, 0.0], status=["detectado", "duvidoso", "interpolado", "detectado"], conf=0.8)
    f = avaliar_trilha(t, "T1", Config())
    assert f.comprimento_m == pytest.approx(30.0)
    assert f.confianca_media == pytest.approx(0.8) and f.frac_duvidosa == pytest.approx(0.25)
    assert f.geometria.geom_type == "LineString" and len(f.geometria.coords) == 4
    with pytest.raises(ErroContrato):
        avaliar_trilha(_trilha([0.0]), "T1", Config())
    assert len(avaliar_trilhas([t, t], "T1", Config())) == 2
