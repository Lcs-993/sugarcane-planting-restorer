import numpy as np
import pytest
from shapely.geometry import box

from deteccao_linhas.config import Config
from deteccao_linhas.pente import ajustar_bloco, ajustar_fase, localizar_dentes
from deteccao_linhas.tipos import Bloco, PerfilLateral


def _perfil(centros, larguras=0.48, t0=0.0, t1=30.0, bin_m=0.06, alturas=1.0, extra=(), cobertura=1.0):
    t = np.arange(t0 + bin_m / 2, t1, bin_m)
    v = np.zeros_like(t)
    larg = np.broadcast_to(larguras, len(centros))
    alt = np.broadcast_to(alturas, len(centros))
    for c, w, a in zip(centros, larg, alt):
        v[np.abs(t - c) <= w / 2] = a
    for c, w, a in extra:
        v[np.abs(t - c) <= w / 2] = a
    bloco = Bloco("B1", "R1", (100.0, 200.0), (0.0, 1.0), (-1.0, 0.0), 0.0, 10.0, t0, t1, 0.0, box(0, 0, 1, 1))
    return PerfilLateral(bloco, t, v, (v > 0.5).astype(float), cobertura)


def test_fileiras_regulares():
    cfg = Config()
    cs = 3.1 + 1.5 * np.arange(16)
    r = ajustar_bloco(_perfil(cs), cfg)
    ts = np.array([p.t_m for p in r.posicoes])
    assert len(ts) == 16
    assert np.allclose(ts, cs, atol=0.04)
    assert all(abs(p.espacamento_vizinha_m - 1.5) < 0.05 for p in r.posicoes[:-1])
    assert r.posicoes[-1].espacamento_vizinha_m is None
    assert not any(p.salto for p in r.posicoes)
    assert all(p.ajuste_pente > 0.8 and p.confianca > 0.8 for p in r.posicoes)
    assert all(0.40 < p.largura_m < 0.56 for p in r.posicoes)
    # x,y no quadro do mapa: origem + s_mid*u + t*n
    p0 = r.posicoes[0]
    assert (p0.x, p0.y) == pytest.approx((100.0 - p0.t_m, 205.0))


def test_salto_entre_passadas_absorvido_e_marcado():
    cfg = Config()
    # passadas de 3 m: pares em 1,5 m; entre passadas o GPS desloca 0,3 m
    cs = []
    for k in range(6):
        base = 3.0 + k * (3.0 + 0.3)
        cs += [base, base + 1.5]
    r = ajustar_bloco(_perfil(cs, t1=34.0), cfg)
    ts = [p.t_m for p in r.posicoes]
    assert len(ts) == 12 and np.allclose(ts, cs, atol=0.05)
    saltos = [p.salto for p in r.posicoes]
    assert sum(saltos) == 5  # um por fronteira de passada (esp. 1,8 m)
    assert all(not saltos[i] for i in range(0, 12, 2))  # esp. 1,5 dentro da passada


def test_pico_fora_do_pente_e_rejeitado():
    cfg = Config()
    cs = 3.1 + 1.5 * np.arange(12)
    erva = (3.1 + 1.5 * 5 + 0.75, 0.3, 0.9)  # entre duas fileiras
    r = ajustar_bloco(_perfil(cs, extra=[erva], t1=24.0), cfg)
    ts = np.array([p.t_m for p in r.posicoes])
    assert len(ts) == 12 and np.allclose(ts, cs, atol=0.05)


def test_fileira_ausente_nao_e_preenchida():
    cfg = Config()
    cs = [3.1 + 1.5 * k for k in range(12) if k != 5]
    r = ajustar_bloco(_perfil(cs, t1=24.0), cfg)
    assert len(r.posicoes) == 11
    k = [i for i, p in enumerate(r.posicoes) if p.salto]
    assert len(k) == 1 and r.posicoes[k[0]].espacamento_vizinha_m == pytest.approx(3.0, abs=0.05)


def test_sem_pico_e_cobertura_baixa():
    cfg = Config()
    vazio = _perfil([], t1=15.0)
    assert ajustar_fase(vazio, cfg) == []
    assert localizar_dentes(vazio, [], cfg) == ()
    assert ajustar_bloco(vazio, cfg).posicoes == () and ajustar_bloco(vazio, cfg).fase_m is None
    baixo = _perfil(3.1 + 1.5 * np.arange(8), t1=15.0, cobertura=0.1)
    assert ajustar_bloco(baixo, cfg).posicoes == ()


def test_fileira_cortada_na_borda_ignorada():
    cfg = Config()
    # fileira em t=0.1 (metade fora do bloco) e outra normal
    r = ajustar_bloco(_perfil([0.1, 1.6, 3.1, 4.6, 6.1], t0=0.0, t1=7.0), cfg)
    assert all(p.t_m > 1.0 for p in r.posicoes)


def test_pico_fraco_tem_confianca_menor():
    cfg = Config()
    cs = 3.1 + 1.5 * np.arange(10)
    alt = np.ones(10)
    alt[4] = 0.3
    r = ajustar_bloco(_perfil(cs, alturas=alt, t1=20.0), cfg)
    conf = {round(p.t_m, 1): p.confianca for p in r.posicoes}
    assert conf[round(cs[4], 1)] < min(v for k, v in conf.items() if k != round(cs[4], 1))
