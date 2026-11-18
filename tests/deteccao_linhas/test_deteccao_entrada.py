import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, box

from deteccao_linhas.config import Config
from deteccao_linhas.entrada import carregar_entrada, verificar_crs
from deteccao_linhas.tipos import ErroContrato, ErroCRS, ErroLeitura


def test_carrega(ortho_simples):
    tif, gpkg = ortho_simples
    d = carregar_entrada(tif, gpkg, Config())
    assert d.crs.equals(CRS.from_epsg(31983))
    assert [t.id for t in d.talhoes] == ["T1"]


def test_arquivo_inexistente(tmp_path, ortho_simples):
    tif, gpkg = ortho_simples
    with pytest.raises(ErroLeitura):
        carregar_entrada(tmp_path / "x.tif", gpkg, Config())
    with pytest.raises(ErroLeitura):
        carregar_entrada(tif, tmp_path / "x.gpkg", Config())


def test_formato_nao_suportado(tmp_path, ortho_simples):
    tif, _ = ortho_simples
    p = tmp_path / "t.geojson"
    p.write_text("{}")
    with pytest.raises(ErroLeitura):
        carregar_entrada(tif, p, Config())


def test_campo_ausente(ortho_simples):
    tif, gpkg = ortho_simples
    with pytest.raises(ErroLeitura):
        carregar_entrada(tif, gpkg, Config(campo_id_talhao="nome"))


def test_crs_divergente(tmp_path, ortho_simples):
    tif, _ = ortho_simples
    g = gpd.GeoDataFrame({"id": ["T1"]}, geometry=[box(-47, -22, -46.9, -21.9)], crs="EPSG:4674")
    p = tmp_path / "t4674.gpkg"
    g.to_file(p, driver="GPKG")
    with pytest.raises(ErroCRS, match="CRS divergente: ortomosaico=EPSG:31983; talhoes=EPSG:4674. "
                                      "Divergem do ortomosaico: talhoes."):
        carregar_entrada(tif, p, Config())


def test_crs_geografico_e_ausente():
    with pytest.raises(ErroCRS):
        verificar_crs({"ortomosaico": CRS.from_epsg(4674), "talhoes": CRS.from_epsg(4674)})
    with pytest.raises(ErroCRS):
        verificar_crs({"ortomosaico": CRS.from_epsg(31983), "talhoes": None})


def test_banda_inexistente(ortho_simples):
    tif, gpkg = ortho_simples
    with pytest.raises(ErroContrato):
        carregar_entrada(tif, gpkg, Config(bandas_rgb=(1, 2, 5)))


def _grava(tmp_path, geoms, ids):
    p = tmp_path / "t.gpkg"
    gpd.GeoDataFrame({"id": ids}, geometry=geoms, crs="EPSG:31983").to_file(p, driver="GPKG")
    return p


def test_talhao_nao_poligono(tmp_path, ortho_simples):
    tif, _ = ortho_simples
    p = _grava(tmp_path, [LineString([(0, 0), (1, 1)])], ["a"])
    with pytest.raises(ErroContrato):
        carregar_entrada(tif, p, Config())


def test_id_duplicado(tmp_path, ortho_simples):
    tif, _ = ortho_simples
    p = _grava(tmp_path, [box(394000, 7774940, 394010, 7774950), box(394020, 7774940, 394030, 7774950)], ["a", "a"])
    with pytest.raises(ErroContrato, match="duplicado"):
        carregar_entrada(tif, p, Config())


def test_talhao_invalido(tmp_path, ortho_simples):
    from shapely.geometry import Polygon
    tif, _ = ortho_simples
    gravata = Polygon([(394000, 7774940), (394010, 7774950), (394010, 7774940), (394000, 7774950)])
    p = _grava(tmp_path, [gravata], ["a"])
    with pytest.raises(ErroContrato):
        carregar_entrada(tif, p, Config())
