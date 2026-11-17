"""Testes do módulo entrada.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, box

import sinteticos as syn
from linhas_plantio.config import Config
from linhas_plantio.entrada import atribuir_talhao, carregar_entrada, verificar_crs
from linhas_plantio.tipos import ErroContrato, ErroCRS, ErroLeitura, Talhao


@pytest.fixture(scope="module")
def caso(tmp_path_factory):
    return syn.gerar_caso(tmp_path_factory.mktemp("entrada"), syn.deriva_constante(), lacunas=[])


def test_carrega_entrada_valida(caso):
    dados = carregar_entrada(caso.raster, caso.talhoes, caso.linhas, Config())
    assert dados.crs.equals(CRS.from_user_input(syn.CRS_SINTETICO))
    assert [t.id for t in dados.talhoes] == ["T1"]
    assert [p.id_passada for p in dados.passadas] == caso.ids_passadas
    assert all(p.talhao == "T1" for p in dados.passadas)


def test_crs_divergente_gera_erro_claro(tmp_path):
    c = syn.gerar_caso(tmp_path, syn.deriva_constante(), lacunas=[], crs_talhoes="EPSG:4674")
    with pytest.raises(ErroCRS) as exc:
        carregar_entrada(c.raster, c.talhoes, c.linhas, Config())
    msg = str(exc.value)
    assert msg.startswith("CRS divergente: ortomosaico=EPSG:31983; talhoes=EPSG:4674; linhas=EPSG:31983.")
    assert "Divergem do ortomosaico: talhoes." in msg
    assert "Reprojete as camadas antes de rodar." in msg


def test_verificar_crs_lista_todas_as_divergentes():
    a, b, c = CRS.from_epsg(31983), CRS.from_epsg(31982), CRS.from_epsg(4674)
    with pytest.raises(ErroCRS, match="Divergem do ortomosaico: talhoes, linhas"):
        verificar_crs({"ortomosaico": a, "talhoes": b, "linhas": c})
    verificar_crs({"ortomosaico": a, "talhoes": CRS.from_epsg(31983), "linhas": a})  # equivalentes: sem erro


def test_crs_ausente_ou_geografico(tmp_path):
    with pytest.raises(ErroCRS, match="ausente"):
        verificar_crs({"ortomosaico": CRS.from_epsg(31983), "talhoes": None})
    g = CRS.from_epsg(4674)
    with pytest.raises(ErroCRS, match="não é projetado em metros"):
        verificar_crs({"ortomosaico": g, "talhoes": g, "linhas": g})


def test_campo_identificador_ausente(caso):
    with pytest.raises(ErroLeitura, match="campo identificador 'codigo' ausente"):
        carregar_entrada(caso.raster, caso.talhoes, caso.linhas, Config(campo_id_talhao="codigo"))


def test_arquivo_inexistente_e_formato(caso, tmp_path):
    with pytest.raises(ErroLeitura, match="não encontrado"):
        carregar_entrada(tmp_path / "x.tif", caso.talhoes, caso.linhas, Config())
    dxf = tmp_path / "linhas.dxf"
    dxf.write_text("x")
    with pytest.raises(ErroLeitura, match="não suportado"):
        carregar_entrada(caso.raster, caso.talhoes, dxf, Config())


def test_banda_inexistente(caso):
    with pytest.raises(ErroContrato, match="não existe"):
        carregar_entrada(caso.raster, caso.talhoes, caso.linhas, Config(indice="ndvi", banda_nir=4))


def test_linha_fora_de_talhao(caso, tmp_path):
    fora = gpd.GeoDataFrame(
        {"id": ["X"]}, geometry=[LineString([(syn.ORIGEM_X + 150, syn.ORIGEM_Y + 10), (syn.ORIGEM_X + 160, syn.ORIGEM_Y + 10)])],
        crs=syn.CRS_SINTETICO,
    )
    p = tmp_path / "fora.gpkg"
    fora.to_file(p, driver="GPKG")
    with pytest.raises(ErroContrato, match="fora de qualquer talhão"):
        carregar_entrada(caso.raster, caso.talhoes, p, Config())


def test_geometria_de_tipo_errado_e_id_duplicado(caso, tmp_path):
    pontos = gpd.GeoDataFrame({"id": ["A"]}, geometry=[Point(syn.ORIGEM_X + 20, syn.ORIGEM_Y + 10)], crs=syn.CRS_SINTETICO)
    p = tmp_path / "pontos.gpkg"
    pontos.to_file(p, driver="GPKG")
    with pytest.raises(ErroContrato, match="não é LineString"):
        carregar_entrada(caso.raster, caso.talhoes, p, Config())
    l1 = LineString([(syn.ORIGEM_X + 10, syn.ORIGEM_Y + 10), (syn.ORIGEM_X + 20, syn.ORIGEM_Y + 10)])
    dup = gpd.GeoDataFrame({"id": ["A", "A"]}, geometry=[l1, l1], crs=syn.CRS_SINTETICO)
    p2 = tmp_path / "dup.gpkg"
    dup.to_file(p2, driver="GPKG")
    with pytest.raises(ErroContrato, match="id duplicado"):
        carregar_entrada(caso.raster, caso.talhoes, p2, Config())


def test_atribuir_talhao_parcial_e_ambiguo():
    t1 = Talhao("A", box(0, 0, 10, 10))
    t2 = Talhao("B", box(5, 0, 20, 10))
    dentro = LineString([(1, 1), (4, 1)])
    assert atribuir_talhao(dentro, (t1,)) == "A"
    with pytest.raises(ErroContrato, match="mais de um talhão"):
        atribuir_talhao(LineString([(6, 1), (9, 1)]), (t1, t2))
    with pytest.raises(ErroContrato, match="fora de qualquer talhão"):
        atribuir_talhao(LineString([(8, 1), (12, 1)]), (t1,))
