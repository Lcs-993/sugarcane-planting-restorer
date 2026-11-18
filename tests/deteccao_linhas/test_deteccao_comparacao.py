import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString

from deteccao_linhas.comparacao import AVISO, carregar_referencia, comparar, distancia_lateral, gravar_diferencas
from deteccao_linhas.config import ConfigComparacao
from deteccao_linhas.saida import gravar_geopackage, numerar_fileiras
from deteccao_linhas.tipos import ErroContrato, ErroCRS, ErroDeteccao, ErroLeitura, FileiraAvaliada, PontoFileira

CRS_M = CRS.from_epsg(31983)
CFG = ConfigComparacao()


def _fil(x, status=None, n=11):
    status = status or ["detectado"] * n
    pts = tuple(PontoFileira(f"B{i}", x, 10.0 * i, 10.0 * i, status[i], 0.9) for i in range(n))
    return FileiraAvaliada("T1", LineString([(p.x, p.y) for p in pts]), pts, 10.0 * (n - 1), 0.9, 0.0)


def _gravar(tmp_path, avs, nome="f.gpkg"):
    fil = numerar_fileiras(avs, (0.0, 1.0), (0.0, 0.0))
    p = tmp_path / nome
    gravar_geopackage(fil, CRS_M, p)
    return p


def _ref(tmp_path, linhas, crs="EPSG:31983", nome="r.gpkg"):
    p = tmp_path / nome
    gpd.GeoDataFrame({"id": [f"L{i}" for i in range(len(linhas))]}, geometry=linhas, crs=crs).to_file(p, driver="GPKG")
    return p


def test_distancia_lateral_sinal():
    ref = (LineString([(0.1, 0), (0.1, 100)]),)
    # ponto em x=0 (oeste da referência), direção norte: esquerda = oeste => detectado à esquerda => +
    assert distancia_lateral(0.0, 50.0, (0.0, 1.0), ref, CFG) == pytest.approx(0.1)
    assert distancia_lateral(0.2, 50.0, (0.0, 1.0), ref, CFG) == pytest.approx(-0.1)
    assert distancia_lateral(0.7, 50.0, (0.0, 1.0), ref, CFG) is None  # a 0,6 m: não pareado
    # linha mais próxima na normal
    ref2 = (LineString([(0.4, 0), (0.4, 100)]), LineString([(-0.1, 0), (-0.1, 100)]))
    assert distancia_lateral(0.0, 50.0, (0.0, 1.0), ref2, CFG) == pytest.approx(-0.1)


def test_comparar_vies_e_estatisticas(tmp_path):
    f = _gravar(tmp_path, [_fil(0.0), _fil(1.5, status=["duvidoso"] * 11)])
    r = _ref(tmp_path, [LineString([(0.1, 0), (0.1, 100)]), LineString([(1.4, 0), (1.4, 100)])])
    rel = comparar(f, r, CFG)
    assert rel.aviso == AVISO == "Referência secundária, não é RTK; não mede acurácia."
    assert rel.n_trechos == 22 and rel.taxa_pareamento == 1.0
    assert rel.cobertura_referencia == pytest.approx(1.0)
    # global usa só detectado/interpolado: fileira 0 (x=0 vs 0,1): +0,1
    assert rel.global_.n == 11 and rel.global_.vies_m == pytest.approx(0.1, abs=1e-9)
    assert rel.global_.mediana_abs_m == pytest.approx(0.1) and rel.global_.p95_abs_m == pytest.approx(0.1)
    # duvidosas aparecem por status: x=1,5 vs 1,4 => detectada à direita da referência => -0,1
    assert rel.por_status["duvidoso"].n == 11 and rel.por_status["duvidoso"].vies_m == pytest.approx(-0.1)
    assert rel.por_fileira["T1-F0001"].n + rel.por_fileira["T1-F0002"].n == 11


def test_nao_pareado_e_cobertura(tmp_path):
    f = _gravar(tmp_path, [_fil(0.0)])
    r = _ref(tmp_path, [LineString([(0.0, 0), (0.0, 50)]), LineString([(5.0, 0), (5.0, 100)])])
    rel = comparar(f, r, CFG)
    assert rel.taxa_pareamento == pytest.approx(6 / 11, abs=0.01)  # só y <= 50 tem referência
    assert rel.cobertura_referencia == pytest.approx(50 / 150, abs=0.02)  # 1ª linha coberta; 2ª (a 5 m) não
    assert rel.global_.media_abs_m == pytest.approx(0.0, abs=1e-9)


def test_taxa_pareamento_parcial(tmp_path):
    f = _gravar(tmp_path, [_fil(0.0)])
    r = _ref(tmp_path, [LineString([(0.0, 0), (0.0, 40)])])  # cobre só os 5 primeiros blocos
    rel = comparar(f, r, CFG)
    assert rel.taxa_pareamento == pytest.approx(5 / 11, abs=0.01)


def test_erros(tmp_path):
    f = _gravar(tmp_path, [_fil(0.0)])
    with pytest.raises(ErroCRS):
        comparar(f, _ref(tmp_path, [LineString([(0, 0), (0, 1)])], crs="EPSG:4674", nome="g.gpkg"), CFG)
    with pytest.raises(ErroLeitura):
        comparar(f, tmp_path / "nao.gpkg", CFG)
    with pytest.raises(ErroContrato):
        from shapely.geometry import Point
        carregar_referencia(_ref(tmp_path, [Point(0, 0)], nome="p.gpkg"), CRS_M, CFG)
    vazio = tmp_path / "v.gpkg"
    gravar_geopackage([], CRS_M, vazio)
    with pytest.raises(ErroDeteccao):
        comparar(vazio, _ref(tmp_path, [LineString([(0, 0), (0, 1)])], nome="h.gpkg"), CFG)


def test_comparar_nao_altera_arquivos_e_grava_diferencas(tmp_path):
    f = _gravar(tmp_path, [_fil(0.0)])
    r = _ref(tmp_path, [LineString([(0.1, -5), (0.1, 105)])])
    antes = (f.read_bytes(), r.read_bytes())
    comparar(f, r, CFG)
    assert (f.read_bytes(), r.read_bytes()) == antes
    out = tmp_path / "d.gpkg"
    gravar_diferencas(f, r, CFG, out)
    g = gpd.read_file(out, layer="diferencas")
    assert len(g) == 11 and g["distancia_m"].iloc[0] == pytest.approx(0.1)
