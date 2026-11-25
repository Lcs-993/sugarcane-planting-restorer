"""Etapa 2 (objetos): superpixels do verde classificados com amostras pontuais.

AVISO: imagem sintética com cores separáveis de propósito; prova o fluxo, não a acurácia (hipótese M7).
"""
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Point, box

from mascaras.cli import main
from mascaras.config import ConfigMascaras
from mascaras.objetos import (ATRIBUTOS_BASE, ATRIBUTOS_POSICAO, abrir_contexto, janela_do_pixel, janelas_fixas,
                              processar_janela)
from mascaras.objetos_modelo import (AreaObjetos, classificar_objetos, ler_amostras, treinar_objetos,
                                     validar_por_talhao)
from mascaras.raster import Grade
from mascaras.tipos import CANA, DANINHA, FUNDO, IGNORADO, ErroContrato
from rasterio.transform import from_origin

from sinteticos_mascaras import CRS_M, ORIGEM, centros_fileiras, gerar_deteccao, gerar_orto, manchas_daninha

CFG = ConfigMascaras(buffer_interno_m=1.0, n_arvores=30, n_jobs=1)


def _talhoes_dois(caminho):
    """Dois talhões (A à esquerda, B à direita) cobrindo os 30 x 30 m sintéticos."""
    x0, y1 = ORIGEM
    gpd.GeoDataFrame({"id": ["A", "B"]}, geometry=[box(x0, y1 - 30, x0 + 15, y1), box(x0 + 15, y1 - 30, x0 + 30, y1)],
                     crs=CRS_M).to_file(caminho, driver="GPKG")
    return caminho


def _amostras(caminho, dan, por_talhao=6):
    """Pontos de cana no eixo das fileiras e de daninha no centro das manchas, nos dois talhões."""
    x0, y1 = ORIGEM
    pts, cls = [], []
    for lado, (xa, xb) in {"A": (2, 13), "B": (17, 28)}.items():
        fil = [x for x in centros_fileiras(30) if xa < x < xb]
        for k in range(por_talhao):
            pts.append(Point(x0 + fil[k % len(fil)], y1 - (4 + 3 * k)))
            cls.append("cana")
        for x, y, _ in [m for m in dan if xa < m[0] < xb and 3 < m[1] < 27][:por_talhao]:
            pts.append(Point(x0 + x, y1 - y))
            cls.append("daninha")
    pts.append(Point(x0 + 0.1, y1 - 0.1))  # fora da área útil
    cls.append("cana")
    gpd.GeoDataFrame({"classe": cls}, geometry=pts, crs=CRS_M).to_file(caminho, driver="GPKG")
    return caminho


@pytest.fixture
def area(tmp_path):
    dan = manchas_daninha(30, 30, n=40, raio_m=0.30, semente=2)
    orto = gerar_orto(tmp_path / "o.tif", daninhas=dan)
    tal = _talhoes_dois(tmp_path / "t.gpkg")
    det = gerar_deteccao(tmp_path / "det.gpkg")
    am = _amostras(tmp_path / "am.gpkg", dan)
    return tmp_path, AreaObjetos(orto, tal, det, am, nome="sint"), dan


def test_janelas_fixas_iguais_no_treino_e_na_classificacao():
    g = Grade(transform=from_origin(0, 5000, 0.06, 0.06), largura=5000, altura=4000, res=0.06)
    jan = list(janelas_fixas(g, (100, 4900, 200, 4950), 1024))
    assert all(l % 1024 == 0 and c % 1024 == 0 for l, c, _, _ in jan)
    for lin, col in [(5, 1700), (3000, 4999)]:
        assert janela_do_pixel(lin, col, g, 1024) in list(janelas_fixas(g, (0, 0, 300, 5000), 1024))


def test_superpixels_so_no_verde_e_posicao(area):
    d, a, dan = area
    ctx = abrir_contexto(a.ortomosaico, a.talhoes, a.deteccao, CFG)
    try:
        jan = processar_janela(ctx, 0, 0, ctx.orto.grade.altura, ctx.orto.grade.largura, CFG, True)
        assert jan.X.shape == (jan.ids.size, len(ATRIBUTOS_BASE) + len(ATRIBUTOS_POSICAO))
        assert np.isfinite(jan.X).all()
        assert not (jan.segmentos[~jan.verde] > 0).any()  # superpixel só em pixel verde
        g = ctx.orto.grade
        def atributos_em(x, y):
            col, lin = ~g.transform * (ORIGEM[0] + x, ORIGEM[1] - y)
            s = jan.segmentos[int(lin), int(col)]
            assert s > 0
            return dict(zip(ATRIBUTOS_BASE + ATRIBUTOS_POSICAO, jan.X[np.searchsorted(jan.ids, s)]))
        na_fileira = atributos_em(centros_fileiras(30)[4], 15)
        x, y, _ = next(m for m in dan if 3 < m[1] < 27 and 2 < m[0] < 28)
        na_mancha = atributos_em(x, y)
        assert na_fileira["dist_media_m"] < 0.2 < na_mancha["dist_media_m"]
    finally:
        ctx.fechar()


def test_treino_validacao_e_classificacao(area):
    d, a, dan = area
    modelo = d / "obj.joblib"
    meta = treinar_objetos([a], modelo, CFG)
    assert meta.amostras_por_classe["cana"] >= 8 and meta.amostras_por_classe["daninha"] >= 6
    assert meta.descartes["fora_da_area_util"] == 1
    v = meta.validacao["com_posicao"]["global"]
    assert set(meta.validacao) == {"com_posicao", "sem_posicao"}
    assert v["acerto_cana"] == 1.0 and v["acerto_daninha"] >= 0.8  # cores separáveis de propósito
    assert modelo.with_suffix(".json").exists()

    saida = d / "m.tif"
    cont = classificar_objetos(AreaObjetos(a.ortomosaico, a.talhoes, a.deteccao), modelo, saida, CFG)
    assert cont["cana"] > 0 and cont["daninha"] > 0 and cont["fundo"] > 0
    with rasterio.open(saida) as ds:
        def px(x, y):
            lin, col = ds.index(ORIGEM[0] + x, ORIGEM[1] - y)
            return int(ds.read(1, window=((lin, lin + 1), (col, col + 1)))[0, 0])
        assert px(centros_fileiras(30)[6], 20) == CANA
        assert px(centros_fileiras(30)[6] + 0.75, 1.9) in (FUNDO, DANINHA)
        x, y, _ = next(m for m in dan if 3 < m[1] < 27 and 2 < m[0] < 28)
        assert px(x, y) == DANINHA
        assert px(0.1, 0.1) == IGNORADO


def test_sem_deteccao_exige_usar_posicao_false(area):
    d, a, _ = area
    sem = AreaObjetos(a.ortomosaico, a.talhoes, None, a.amostras, nome="sint")
    with pytest.raises(ErroContrato, match="usar_posicao"):
        treinar_objetos([sem], d / "m.joblib", CFG)
    meta = treinar_objetos([sem], d / "m.joblib", ConfigMascaras(buffer_interno_m=1.0, n_arvores=10, n_jobs=1,
                                                                 usar_posicao=False))
    assert meta.atributos == ATRIBUTOS_BASE and set(meta.validacao) == {"sem_posicao"}


def test_amostra_com_classe_invalida(tmp_path):
    p = tmp_path / "a.gpkg"
    gpd.GeoDataFrame({"classe": ["capim"]}, geometry=[Point(ORIGEM)], crs=CRS_M).to_file(p, driver="GPKG")
    with pytest.raises(ErroContrato, match="classe"):
        ler_amostras(p, CRS_M)


def test_validacao_pula_talhao_sem_as_duas_classes_no_treino():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(12, 3)).astype(np.float32)
    y = np.array([CANA] * 6 + [DANINHA] * 6, dtype=np.uint8)
    grupos = np.array(["t1"] * 6 + ["t2"] * 6)  # cada talhão tem uma classe só
    r = validar_por_talhao(X, y, grupos, ConfigMascaras(n_arvores=5, n_jobs=1))
    assert r["global"] is None and set(r["pulados"]) == {"t1", "t2"}


def test_cli(area, capsys):
    d, a, _ = area
    cfgp = d / "c.yaml"
    cfgp.write_text("buffer_interno_m: 1.0\nn_arvores: 10\nn_jobs: 1\n", encoding="utf-8")
    assert main(["objetos-treinar", "--area", str(a.ortomosaico), str(a.talhoes), str(a.deteccao), str(a.amostras),
                 "--modelo", str(d / "m.joblib"), "--config", str(cfgp)]) == 0
    assert "deixando um talhão de fora" in capsys.readouterr().out
    assert main(["objetos-classificar", "--ortomosaico", str(a.ortomosaico), "--talhoes", str(a.talhoes),
                 "--deteccao", str(a.deteccao), "--modelo", str(d / "m.joblib"), "--saida", str(d / "s.tif"),
                 "--config", str(cfgp)]) == 0
    # modelo do nível 1 não serve para objetos-classificar
    assert main(["objetos-classificar", "--ortomosaico", str(a.ortomosaico), "--talhoes", str(a.talhoes),
                 "--modelo", str(d / "nao.joblib"), "--saida", str(d / "s2.tif")]) == 2
