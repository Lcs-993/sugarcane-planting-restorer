"""Detecção com perfil sobre a máscara de classes (docs/escopo-mascaras.md, seção 5).

AVISO: testes sintéticos mostram que o fluxo funciona, não a acurácia em campo.
"""
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from deteccao_linhas.cli import executar_deteccao, main
from deteccao_linhas.config import Config
from deteccao_linhas.fonte_mascara import abrir_fonte_mascara, abrir_raster_mascara
from deteccao_linhas.indice_binarizacao import recortar_talhao
from deteccao_linhas.tipos import ErroConfig, ErroCRS, Talhao

from conftest import gerar_fileiras, gerar_talhao

ORIGEM = (394000.0, 7775000.0)
CFG = Config(regiao_m=50, area_minima_regiao_m2=500, comprimento_min_fileira_m=20)


def gerar_mascara(caminho, *, lado_m=60.0, res=0.06, fase=0.3, daninha_entre=False, sombra=None, crs="EPSG:31983"):
    """Máscara de classes com fileiras norte-sul: 1 cana, 3 fundo; opcionalmente faixas de daninha (2) no meio
    das entrelinhas e um retângulo de sombra (4) em coordenadas relativas (x0, y0, x1, y1), y para o sul."""
    n = int(round(lado_m / res))
    X, Y = np.meshgrid((np.arange(n) + 0.5) * res, (np.arange(n) + 0.5) * res)
    d = np.abs(((X - fase + 0.75) % 1.5) - 0.75)
    cls = np.where(d <= 0.24, 1, 3).astype(np.uint8)
    if daninha_entre:
        cls[np.abs(d - 0.75) <= 0.10] = 2
    if sombra is not None:
        x0, y0, x1, y1 = sombra
        cls[(X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)] = 4
    with rasterio.open(caminho, "w", driver="GTiff", width=n, height=n, count=1, dtype="uint8", crs=crs,
                       transform=from_origin(ORIGEM[0], ORIGEM[1], res, res), nodata=0) as ds:
        ds.write(cls, 1)
    return caminho


@pytest.fixture
def area(tmp_path):
    tif = gerar_fileiras(tmp_path / "o.tif", origem=ORIGEM, ruido=4.0)
    tal = gerar_talhao(tmp_path / "t.gpkg", (ORIGEM[0], ORIGEM[1] - 60, ORIGEM[0] + 60, ORIGEM[1]))
    return tmp_path, tif, tal


def test_valores_e_validade(tmp_path):
    m = gerar_mascara(tmp_path / "m.tif", daninha_entre=True, sombra=(10, 10, 20, 20))
    r = abrir_raster_mascara(m, "EPSG:31983", 0.06)
    try:
        area = recortar_talhao(Talhao("T1", box(ORIGEM[0], ORIGEM[1] - 60, ORIGEM[0] + 60, ORIGEM[1])), CFG)
        f = abrir_fonte_mascara(r, area, 0.06)
        j = f.ler_janela((ORIGEM[0] + 5, ORIGEM[1] - 25, ORIGEM[0] + 25, ORIGEM[1] - 5))
        assert j.valores.dtype == bool and j.valores.shape == j.validade.shape
        assert not j.valores[~j.validade].any()
        x, y = j.transform * (0, 0)
        # dentro da sombra: inválido; fora: cana verdadeira só nas faixas; daninha válida e False
        lin_s, col_s = int((y - (ORIGEM[1] - 15)) / 0.06), int(((ORIGEM[0] + 15) - x) / 0.06)
        assert not j.validade[lin_s, col_s]
        frac = j.valores[j.validade].mean()
        assert frac == pytest.approx(0.48 / 1.5, abs=0.03)
    finally:
        r.fechar()


def test_resolucao_diferente_e_crs(tmp_path):
    m = gerar_mascara(tmp_path / "m.tif", res=0.09)
    with pytest.raises(ErroConfig, match="resolucao_trabalho_m"):
        abrir_raster_mascara(m, "EPSG:31983", 0.06)
    m2 = gerar_mascara(tmp_path / "m2.tif", crs="EPSG:31982")
    with pytest.raises(ErroCRS):
        abrir_raster_mascara(m2, "EPSG:31983", 0.06)


def test_config_mascara_exige_caminho():
    with pytest.raises(ErroConfig, match="caminho_mascara"):
        Config(perfil_sobre="mascara")
    assert Config(perfil_sobre="mascara", caminho_mascara="x.tif").perfil_sobre == "mascara"


def test_deteccao_sobre_mascara_ponta_a_ponta(area):
    d, tif, tal = area
    m = gerar_mascara(d / "m.tif", daninha_entre=True)
    cfg = Config(**{**CFG.__dict__, "perfil_sobre": "mascara", "caminho_mascara": str(m)})
    saida = d / "f.gpkg"
    resumos = executar_deteccao(tif, tal, saida, cfg)
    assert np.isnan(resumos[0].limiar_otsu)
    f = gpd.read_file(saida, layer="fileiras")
    assert len(f) >= 30
    xs = sorted(float(np.median([c[0] for c in g.coords])) - ORIGEM[0] for g in f.geometry)
    residuo = [abs(((x - 0.3 + 0.75) % 1.5) - 0.75) for x in xs]
    assert max(residuo) < 0.06  # as fileiras caem nas faixas de cana, não na daninha das entrelinhas


def test_cli_opcao_mascara(area, capsys):
    d, tif, tal = area
    m = gerar_mascara(d / "m.tif")
    cfgp = d / "c.yaml"
    cfgp.write_text("regiao_m: 50\narea_minima_regiao_m2: 500\ncomprimento_min_fileira_m: 20\n", encoding="utf-8")
    rc = main(["detectar", "--ortomosaico", str(tif), "--talhoes", str(tal), "--saida", str(d / "f.gpkg"),
               "--config", str(cfgp), "--mascara", str(m)])
    assert rc == 0
    assert "máscara de classes" in capsys.readouterr().out
    rc = main(["detectar", "--ortomosaico", str(tif), "--talhoes", str(tal), "--saida", str(d / "g.gpkg"),
               "--config", str(cfgp), "--mascara", str(d / "nao.tif")])
    assert rc == 2
