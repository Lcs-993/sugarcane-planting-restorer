"""Fluxo completo sobre imagem sintética: pseudo-rótulos -> treino -> classificação -> avaliação.

AVISO: prova que o fluxo funciona, não a acurácia. As cores sintéticas são separáveis de propósito.
"""
import json

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Point, box

from mascaras.avaliacao import avaliar
from mascaras.cli import main
from mascaras.config import ConfigMascaras
from mascaras.inferencia import classificar
from mascaras.pseudo_rotulos import gerar_pseudo_rotulos
from mascaras.tipos import CANA, DANINHA, FUNDO, IGNORADO, ErroContrato, ErroLeitura
from mascaras.treino import ParTreino, treinar

from sinteticos_mascaras import (CRS_M, ORIGEM, centros_fileiras, gerar_deteccao, gerar_orto, gerar_talhao,
                                 manchas_daninha)

# daninha_por_posicao=True para exercitar as três classes no fluxo; o padrão está em test_padrao_foco_na_cana
CFG = ConfigMascaras(buffer_interno_m=1.0, n_arvores=20, max_amostras_por_classe=4000, n_jobs=1,
                     daninha_por_posicao=True)


@pytest.fixture
def area(tmp_path):
    dan = manchas_daninha(30, 30, n=15)
    orto = gerar_orto(tmp_path / "o.tif", daninhas=dan)
    tal = gerar_talhao(tmp_path / "t.gpkg")
    det = gerar_deteccao(tmp_path / "det.gpkg")
    return tmp_path, orto, tal, det, dan


def _px(ds, x_rel, y_sul):
    lin, col = ds.index(ORIGEM[0] + x_rel, ORIGEM[1] - y_sul)
    return int(ds.read(1, window=((lin, lin + 1), (col, col + 1)))[0, 0])


def test_pseudo_rotulos_classes_nos_lugares_certos(area):
    d, orto, tal, det, dan = area
    saida = d / "rot.tif"
    res = gerar_pseudo_rotulos(orto, tal, det, saida, CFG)
    assert res.pixels_por_classe["cana"] > 0 and res.pixels_por_classe["daninha"] > 0
    assert res.comprimento_confiavel_m > 0.8 * res.comprimento_total_m
    assert json.loads(saida.with_suffix(".json").read_text(encoding="utf-8"))["talhoes"] == ["T1"]
    x0 = centros_fileiras(30)[3]
    with rasterio.open(saida) as ds:
        assert ds.crs.to_epsg() == 31983 and abs(ds.transform.a - 0.06) < 1e-9
        assert _px(ds, x0, 15) == CANA
        assert _px(ds, x0 + 0.40, 15) in (IGNORADO, FUNDO)  # margem: verde seria ignorado, solo é fundo
        x, y, _ = next(m for m in dan if 2 < m[1] < 24)  # dentro da zona (as fileiras vão de 0,5 a 25,5 m)
        assert _px(ds, x, y) == DANINHA
        assert _px(ds, 0.1, 0.1) == IGNORADO  # fora da área útil


def test_trecho_duvidoso_fica_ignorado(area):
    d, orto, tal, _, _ = area
    det = gerar_deteccao(d / "det2.gpkg", status=lambda i, j: ("duvidoso", 0.3) if i == 3 else ("detectado", 0.9))
    gerar_pseudo_rotulos(orto, tal, det, d / "rot2.tif", CFG)
    with rasterio.open(d / "rot2.tif") as ds:
        assert _px(ds, centros_fileiras(30)[3], 15) == IGNORADO
        assert _px(ds, centros_fileiras(30)[4], 15) == CANA


def test_correcao_manual_sobrescreve(area):
    d, orto, tal, det, _ = area
    x0 = ORIGEM[0] + centros_fileiras(30)[3]
    corr = d / "corr.gpkg"
    gpd.GeoDataFrame({"classe": ["daninha"]}, geometry=[box(x0 - 0.3, ORIGEM[1] - 16, x0 + 0.3, ORIGEM[1] - 14)],
                     crs=CRS_M).to_file(corr, driver="GPKG")
    res = gerar_pseudo_rotulos(orto, tal, det, d / "rot3.tif", CFG, caminho_correcoes=corr)
    assert res.n_poligonos_correcao == 1
    with rasterio.open(d / "rot3.tif") as ds:
        assert _px(ds, centros_fileiras(30)[3], 15) == DANINHA


def test_correcao_com_classe_invalida(area):
    d, orto, tal, det, _ = area
    corr = d / "c.gpkg"
    gpd.GeoDataFrame({"classe": [9]}, geometry=[box(ORIGEM[0], ORIGEM[1] - 2, ORIGEM[0] + 2, ORIGEM[1])],
                     crs=CRS_M).to_file(corr, driver="GPKG")
    with pytest.raises(ErroContrato, match="classe"):
        gerar_pseudo_rotulos(orto, tal, det, d / "r.tif", CFG, caminho_correcoes=corr)


def test_deteccao_sem_camadas(area):
    d, orto, tal, _, _ = area
    outro = d / "x.gpkg"
    gpd.GeoDataFrame({"a": [1]}, geometry=[Point(ORIGEM)], crs=CRS_M).to_file(outro, layer="outra", driver="GPKG")
    with pytest.raises(ErroLeitura, match="fileiras"):
        gerar_pseudo_rotulos(orto, tal, outro, d / "r.tif", CFG)


def test_treino_classificacao_e_avaliacao(area):
    d, orto, tal, det, dan = area
    rot = d / "rot.tif"
    gerar_pseudo_rotulos(orto, tal, det, rot, CFG)
    modelo = d / "modelo" / "m.joblib"
    meta = treinar([ParTreino(orto, rot)], modelo, CFG)
    assert modelo.exists() and modelo.with_suffix(".json").exists()
    assert set(meta.classes.values()) >= {"cana", "daninha", "fundo"}
    assert meta.talhoes_treino == ["T1"]

    # classifica um ortomosaico novo (outra semente de ruído e outras manchas)
    orto2 = gerar_orto(d / "o2.tif", daninhas=manchas_daninha(30, 30, n=10, semente=7), semente=3)
    masc = d / "masc.tif"
    cfg = ConfigMascaras(buffer_interno_m=1.0, gravar_probabilidade_cana=True)
    res = classificar(orto2, tal, modelo, masc, cfg)
    assert res.caminho_probabilidade and (d / "masc_prob_cana.tif").exists()
    with rasterio.open(masc) as ds:
        assert ds.dtypes[0] == "uint8" and abs(ds.transform.a - 0.06) < 1e-9
        a = ds.read(1)
        assert _px(ds, centros_fileiras(30)[5], 12) == CANA
        assert _px(ds, centros_fileiras(30)[5] + 0.75, 12) in (FUNDO, DANINHA)
        assert _px(ds, 0.1, 0.1) == IGNORADO
    frac_cana = (a == CANA).sum() / (a != IGNORADO).sum()
    assert frac_cana == pytest.approx(0.48 / 1.5, abs=0.06)

    # avaliação contra polígonos de teste "manuais" (aqui, gerados a partir da geometria conhecida)
    x = ORIGEM[0] + centros_fileiras(30)[5]
    teste = d / "teste.gpkg"
    gpd.GeoDataFrame({"classe": [CANA, FUNDO]},
                     geometry=[box(x - 0.15, ORIGEM[1] - 20, x + 0.15, ORIGEM[1] - 5),
                               box(x + 0.6, ORIGEM[1] - 20, x + 0.9, ORIGEM[1] - 5)], crs=CRS_M).to_file(
        teste, driver="GPKG")
    rel = avaliar(masc, teste)
    assert rel.n_pixels > 0 and rel.iou_por_classe["cana"] > 0.9
    assert "RTK" in rel.aviso


def test_treino_sem_cana(area):
    d, orto, tal, det, _ = area
    rot = d / "rot.tif"
    gerar_pseudo_rotulos(orto, tal, det, rot, CFG)
    with rasterio.open(rot, "r+") as ds:
        a = ds.read(1)
        a[a == CANA] = IGNORADO
        ds.write(a, 1)
    with pytest.raises(ErroContrato, match="cana"):
        treinar([ParTreino(orto, rot)], d / "m.joblib", CFG)


def test_rotulos_fora_da_grade(area):
    d, orto, tal, det, _ = area
    rot = d / "rot.tif"
    gerar_pseudo_rotulos(orto, tal, det, rot, ConfigMascaras(buffer_interno_m=1.0, resolucao_trabalho_m=0.09))
    with pytest.raises(ErroContrato, match="grade"):
        treinar([ParTreino(orto, rot)], d / "m.joblib", CFG)


def test_cli_ponta_a_ponta(area, capsys):
    d, orto, tal, det, _ = area
    cfgp = d / "cfg.yaml"
    cfgp.write_text("buffer_interno_m: 1.0\nn_arvores: 10\nmax_amostras_por_classe: 2000\nn_jobs: 1\n",
                    encoding="utf-8")
    assert main(["pseudo-rotulos", "--ortomosaico", str(orto), "--talhoes", str(tal), "--deteccao", str(det),
                 "--saida", str(d / "r.tif"), "--config", str(cfgp)]) == 0
    assert main(["treinar", "--par", str(orto), str(d / "r.tif"), "--modelo", str(d / "m.joblib"),
                 "--config", str(cfgp)]) == 0
    assert main(["classificar", "--ortomosaico", str(orto), "--talhoes", str(tal), "--modelo", str(d / "m.joblib"),
                 "--saida", str(d / "mc.tif"), "--config", str(cfgp)]) == 0
    assert main(["classificar", "--ortomosaico", str(orto), "--talhoes", str(tal), "--modelo", str(d / "nao.joblib"),
                 "--saida", str(d / "mc2.tif")]) == 2
    assert "não encontrado" in capsys.readouterr().err


def test_padrao_foco_na_cana(area):
    """Padrão: nenhuma daninha por posição; a mancha entre fileiras fica ignorada e o modelo aprende cana x fundo."""
    d, orto, tal, det, dan = area
    cfg = ConfigMascaras(buffer_interno_m=1.0, n_arvores=10, max_amostras_por_classe=2000, n_jobs=1)
    res = gerar_pseudo_rotulos(orto, tal, det, d / "rot_cana.tif", cfg)
    assert res.pixels_por_classe["daninha"] == 0 and res.pixels_por_classe["cana"] > 0
    with rasterio.open(d / "rot_cana.tif") as ds:
        x, y, _ = next(m for m in dan if 2 < m[1] < 24)
        assert _px(ds, x, y) == IGNORADO
    meta = treinar([ParTreino(orto, d / "rot_cana.tif")], d / "m.joblib", cfg)
    assert set(meta.classes.values()) == {"cana", "fundo"}
