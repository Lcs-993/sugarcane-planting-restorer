import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString

from deteccao_linhas.saida import gravar_geopackage, numerar_fileiras
from deteccao_linhas.tipos import ErroContrato, ErroLeitura, FileiraAvaliada, PontoFileira


def _av(x, talhao="T1", status="detectado"):
    pts = tuple(PontoFileira(f"B{i}", x, 10.0 * i, 10.0 * i, status, 0.9) for i in range(4))
    return FileiraAvaliada(talhao, LineString([(p.x, p.y) for p in pts]), pts, 30.0, 0.9, 0.0)


def test_numeracao_da_direita_para_a_esquerda():
    # u_ref = norte; n_ref = (-1, 0): t_g cresce para o oeste; ordem crescente = leste -> oeste
    av = [_av(100.0), _av(103.0), _av(101.5)]
    fil = numerar_fileiras(av, (0.0, 1.0), (101.0, 0.0))
    assert [f.id_fileira for f in fil] == ["T1-F0001", "T1-F0002", "T1-F0003"]
    assert [f.avaliada.pontos[0].x for f in fil] == [103.0, 101.5, 100.0]


def test_numeracao_por_talhao():
    fil = numerar_fileiras([_av(1.0, "A"), _av(2.0, "B"), _av(0.0, "A")], (0.0, 1.0), (0.0, 0.0))
    assert sorted(f.id_fileira for f in fil) == ["A-F0001", "A-F0002", "B-F0001"]


def test_geopackage_ida_e_volta(tmp_path):
    fil = numerar_fileiras([_av(1.0), _av(2.5, status="duvidoso")], (0.0, 1.0), (0.0, 0.0))
    out = tmp_path / "s.gpkg"
    crs = CRS.from_epsg(31983)
    gravar_geopackage(fil, crs, out)
    gravar_geopackage(fil, crs, out)  # sobrescreve
    f = gpd.read_file(out, layer="fileiras")
    t = gpd.read_file(out, layer="trechos")
    assert f.crs.equals(crs) and t.crs.equals(crs)
    assert set(f.columns) >= {"id_fileira", "talhao", "comprimento_m", "confianca_media", "frac_duvidosa"}
    assert set(t.columns) >= {"id_fileira", "posicao_m", "status", "confianca"}
    assert len(f) == 2 and len(t) == 8 and set(t.status) == {"detectado", "duvidoso"}


def test_status_invalido_e_caminho_nao_gravavel(tmp_path):
    bad = numerar_fileiras([_av(1.0, status="ok")], (0.0, 1.0), (0.0, 0.0))
    with pytest.raises(ErroContrato):
        gravar_geopackage(bad, CRS.from_epsg(31983), tmp_path / "x.gpkg")
    good = numerar_fileiras([_av(1.0)], (0.0, 1.0), (0.0, 0.0))
    with pytest.raises(ErroLeitura):
        gravar_geopackage(good, CRS.from_epsg(31983), tmp_path / "nao_existe" / "x.gpkg")
