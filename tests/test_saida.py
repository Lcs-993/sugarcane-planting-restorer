"""Testes do módulo saida.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
from dataclasses import replace

import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString

from linhas_plantio.saida import gravar_geopackage
from linhas_plantio.tipos import ErroContrato, ErroLeitura, EstacaoDesvio, Passada, ResultadoPassada

CRS31983 = CRS.from_epsg(31983)
OX, OY = 700000.0, 7800000.0


def resultado(desvios=(0.3, None, 0.3), status=("detectado", "duvidoso", "interpolado")):
    p = Passada("P0", "T1", LineString([(OX, OY), (OX + 20, OY)]))
    ests = tuple(
        EstacaoDesvio("P0", "T1", 10.0 * i, OX + 10.0 * i, OY, (0.0, 1.0), d, 1.5, 0.48, 0.48, st, 0.7)
        for i, (d, st) in enumerate(zip(desvios, status))
    )
    return ResultadoPassada(p, ests, LineString([(OX, OY + 0.3), (OX + 20, OY + 0.3)]), 1 / 3, 1 / 3, True)


def test_grava_camadas_e_atributos(tmp_path):
    saida = tmp_path / "saida.gpkg"
    gravar_geopackage([resultado()], CRS31983, saida)
    lin = gpd.read_file(saida, layer="linhas_corrigidas")
    est = gpd.read_file(saida, layer="estacoes")
    assert lin.crs.equals(CRS31983) and est.crs.equals(CRS31983)
    assert list(lin.columns) == ["id_passada", "talhao", "n_estacoes", "frac_duvidosa", "frac_interpolada", "revisao_manual", "geometry"]
    assert list(est.columns) == ["id_passada", "talhao", "estacao_m", "desvio_m", "status", "confianca", "geometry"]
    assert len(lin) == 1 and len(est) == 3
    assert lin.loc[0, "n_estacoes"] == 3 and bool(lin.loc[0, "revisao_manual"]) is True
    assert est["status"].tolist() == ["detectado", "duvidoso", "interpolado"]
    assert est.loc[1, "desvio_m"] != est.loc[1, "desvio_m"]  # nulo gravado como NaN/nulo


def test_ponto_da_estacao_fica_deslocado_pelo_desvio(tmp_path):
    saida = tmp_path / "s.gpkg"
    gravar_geopackage([resultado()], CRS31983, saida)
    est = gpd.read_file(saida, layer="estacoes")
    assert est.geometry[0].y == pytest.approx(OY + 0.3) and est.geometry[0].x == pytest.approx(OX)
    assert est.geometry[1].y == pytest.approx(OY)  # sem desvio: na posição projetada


def test_status_invalido_e_sem_resultados(tmp_path):
    r = resultado()
    ruim = replace(r, estacoes=(replace(r.estacoes[0], status="ok"),) + r.estacoes[1:])
    with pytest.raises(ErroContrato, match="status inválido"):
        gravar_geopackage([ruim], CRS31983, tmp_path / "x.gpkg")
    with pytest.raises(ErroContrato, match="nenhum resultado"):
        gravar_geopackage([], CRS31983, tmp_path / "x.gpkg")


def test_caminho_nao_gravavel(tmp_path):
    arq = tmp_path / "arquivo.txt"
    arq.write_text("x")
    with pytest.raises(ErroLeitura, match="não foi possível gravar"):
        gravar_geopackage([resultado()], CRS31983, arq / "dentro.gpkg")
