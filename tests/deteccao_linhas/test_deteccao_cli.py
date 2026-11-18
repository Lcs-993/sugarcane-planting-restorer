import inspect
import json
import math

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from deteccao_linhas import cli
from deteccao_linhas.cli import executar_deteccao, main
from deteccao_linhas.config import Config

from conftest import gerar_fileiras, gerar_talhao

ORIGEM = (394000.0, 7775000.0)
ALTURA = 80.0
ANG = 12.0
FASE = 0.3


@pytest.fixture
def cena(tmp_path):
    tif = gerar_fileiras(tmp_path / "o.tif", largura_m=80, altura_m=ALTURA, angulo_graus=ANG, fase_m=FASE,
                         origem=ORIGEM, ruido=4.0)
    gpkg = gerar_talhao(tmp_path / "t.gpkg", (ORIGEM[0], ORIGEM[1] - ALTURA, ORIGEM[0] + 80, ORIGEM[1]))
    return tif, gpkg


def _t_verdadeiro(x, y):
    a = math.radians(ANG)
    X, Y = x - ORIGEM[0], y - (ORIGEM[1] - ALTURA)
    return X * math.cos(a) - Y * math.sin(a)


def test_deteccao_ponta_a_ponta_sintetica(cena, tmp_path):
    tif, gpkg = cena
    out = tmp_path / "saida.gpkg"
    cfg = Config(regiao_m=50.0, area_minima_regiao_m2=500.0, comprimento_min_fileira_m=20.0)
    resumos = executar_deteccao(tif, gpkg, out, cfg)
    assert len(resumos) == 1 and resumos[0].n_fileiras >= 8
    f = gpd.read_file(out, layer="fileiras")
    t = gpd.read_file(out, layer="trechos")
    assert f.crs.to_epsg() == 31983
    assert f["id_fileira"].is_unique and f["id_fileira"].iloc[0] == "T1-F0001"
    # cada ponto detectado cai numa fileira verdadeira (t = FASE + k*1,5), erro < 0,1 m no sintético
    res = [((_t_verdadeiro(p.x, p.y) - FASE + 0.75) % 1.5) - 0.75 for p in t.geometry]
    assert np.median(np.abs(res)) < 0.06 and np.percentile(np.abs(res), 95) < 0.12
    assert (t["status"] == "detectado").mean() > 0.9


def test_cli_erros_e_codigos(cena, tmp_path, capsys):
    tif, gpkg = cena
    assert main(["detectar", "--ortomosaico", str(tmp_path / "x.tif"), "--talhoes", str(gpkg),
                 "--saida", str(tmp_path / "s.gpkg")]) == 2
    assert "Erro:" in capsys.readouterr().err
    # solo puro: nenhuma fileira detectável (erro de detecção, código 2)
    solo = gerar_fileiras(tmp_path / "solo.tif", largura_m=60, altura_m=60, largura_faixa_m=0.0)
    gt = gerar_talhao(tmp_path / "ts.gpkg", (ORIGEM[0], ORIGEM[1] - 60, ORIGEM[0] + 60, ORIGEM[1]))
    assert main(["detectar", "--ortomosaico", str(solo), "--talhoes", str(gt), "--saida", str(tmp_path / "s.gpkg")]) == 2


def test_cli_ponta_a_ponta_com_comparacao(cena, tmp_path, capsys):
    tif, gpkg = cena
    cfgy = tmp_path / "c.yaml"
    cfgy.write_text("regiao_m: 50\narea_minima_regiao_m2: 500\ncomprimento_min_fileira_m: 20\n")
    out = tmp_path / "s.gpkg"
    assert main(["detectar", "--ortomosaico", str(tif), "--talhoes", str(gpkg), "--saida", str(out),
                 "--config", str(cfgy)]) == 0
    # referência: fileiras verdadeiras deslocadas 0,1 m (linhas retas no azimute ANG)
    a = math.radians(ANG)
    u, n = (math.sin(a), math.cos(a)), (math.cos(a), -math.sin(a))  # n aqui = direção de t crescente
    base = (ORIGEM[0], ORIGEM[1] - ALTURA)
    linhas = []
    for k in range(-2, 60):
        tk = FASE + 1.5 * k + 0.1
        p0 = (base[0] + tk * n[0] - 40 * u[0], base[1] + tk * n[1] - 40 * u[1])
        linhas.append(LineString([p0, (p0[0] + 200 * u[0], p0[1] + 200 * u[1])]))
    ref = tmp_path / "r.gpkg"
    gpd.GeoDataFrame({"id": range(len(linhas))}, geometry=linhas, crs="EPSG:31983").to_file(ref, driver="GPKG")
    rel = tmp_path / "rel.json"
    assert main(["comparar", "--fileiras", str(out), "--referencia", str(ref), "--relatorio", str(rel),
                 "--saida-diferencas", str(tmp_path / "dif.gpkg")]) == 0
    txt = capsys.readouterr().out
    assert "Referência secundária, não é RTK; não mede acurácia." in txt
    j = json.loads(rel.read_text(encoding="utf-8"))
    assert j["aviso"].startswith("Referência secundária")
    assert j["taxa_pareamento"] > 0.9
    # referência 0,1 m na direção de t crescente: |viés| ~ 0,1 (sinal fixado por convenção, não conferido aqui)
    assert abs(abs(j["global_"]["vies_m"]) - 0.1) < 0.06


def test_deteccao_nao_aceita_linhas():
    assert set(inspect.signature(cli.executar_deteccao).parameters) == {
        "caminho_ortomosaico", "caminho_talhoes", "caminho_saida", "cfg"}
    import deteccao_linhas, pathlib
    for p in pathlib.Path(deteccao_linhas.__file__).parent.glob("*.py"):
        for linha in p.read_text(encoding="utf-8").splitlines():
            assert not (linha.lstrip().startswith(("import linhas_plantio", "from linhas_plantio"))), p.name
