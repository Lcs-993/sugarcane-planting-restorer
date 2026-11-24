"""Testes de unidade do pacote mascaras: configuração, atributos, grade, Otsu, regras e IoU."""
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from mascaras.atributos import calcular_atributos, exg_normalizado, gli, nomes_atributos
from mascaras.avaliacao import iou_por_classe, matriz_confusao
from mascaras.config import ConfigMascaras, carregar_config
from mascaras.pseudo_rotulos import otsu_histograma, rotular_janela, trechos_confiaveis
from mascaras.raster import Ortomosaico, verificar_crs
from mascaras.tipos import CANA, DANINHA, FUNDO, IGNORADO, SOMBRA, ErroConfig, ErroCRS

from sinteticos_mascaras import gerar_orto


# ---------------------------------------------------------------- configuração

def test_config_padrao_e_yaml(tmp_path):
    assert ConfigMascaras().resolucao_trabalho_m == 0.06
    p = tmp_path / "c.yaml"
    p.write_text("n_arvores: 10\natributos: [r, g, exg]\ngravar_probabilidade_cana: true\n", encoding="utf-8")
    c = carregar_config(p)
    assert c.n_arvores == 10 and c.atributos == ("r", "g", "exg") and c.gravar_probabilidade_cana
    p.write_text("nao_existe: 1\n", encoding="utf-8")
    with pytest.raises(ErroConfig, match="desconhecidos"):
        carregar_config(p)


def test_config_de_exemplo_igual_aos_padroes():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[2]
    assert carregar_config(raiz / "config_mascaras.yaml") == ConfigMascaras()


@pytest.mark.parametrize("kw", [
    {"atributos": ("r", "ndvi")}, {"atributos": ()}, {"lado_janela_px": 300}, {"resolucao_trabalho_m": 0},
    {"limiar_confianca_pseudo": 1.5}, {"meia_largura_zona_m": 0.3}, {"raio_vizinhanca_px": -1},
])
def test_config_invalida(kw):
    with pytest.raises(ErroConfig):
        ConfigMascaras(**kw)


# ---------------------------------------------------------------- atributos

def test_indices():
    b = np.array([60, 160, 50], dtype=np.float32).reshape(3, 1, 1)
    assert exg_normalizado(b)[0, 0] == pytest.approx((320 - 110) / 270)
    assert gli(b)[0, 0] == pytest.approx((320 - 110) / (320 + 110))
    assert np.isnan(exg_normalizado(np.zeros((3, 1, 1))))[0, 0]


def test_atributos_ordem_e_vizinhanca():
    rng = np.random.default_rng(0)
    b = rng.integers(0, 255, (3, 20, 20)).astype(np.float32)
    a = calcular_atributos(b, ("r", "exg"), 0)
    assert a.shape == (2, 20, 20)
    assert np.allclose(a[0], b[0] / 255)
    a2 = calcular_atributos(b, ("r", "exg"), 2)
    assert a2.shape == (4, 20, 20)
    assert nomes_atributos(("r", "exg"), 2) == ["r", "exg", "exg_media_viz", "exg_desvio_viz"]
    assert (a2[3] >= 0).all()


# ---------------------------------------------------------------- grade e CRS

def test_grade_alinhada_e_leitura_com_borda(tmp_path):
    tif = gerar_orto(tmp_path / "o.tif", largura_m=6, altura_m=6, res_m=0.03)
    o = Ortomosaico(tif, (1, 2, 3), 0.06)
    try:
        g = o.grade
        assert (g.largura, g.altura) == (100, 100)
        assert g.transform.c == o.bounds[0] and g.transform.f == o.bounds[3]
        dados, valido = o.ler(0, 0, 10, 10, borda=3)
        assert dados.shape == (3, 16, 16)
        assert not valido[:3].any() and not valido[:, :3].any()  # borda fora do ortomosaico
        assert valido[3:, 3:].all()
        with pytest.raises(ErroConfig):
            Ortomosaico(tif, (1, 2, 3), 0.01)
    finally:
        o.fechar()


def test_crs_divergente_e_geografico():
    with pytest.raises(ErroCRS, match="divergente"):
        verificar_crs({"a": "EPSG:31983", "b": "EPSG:31982"})
    with pytest.raises(ErroCRS, match="metros"):
        verificar_crs({"a": "EPSG:4326"})
    with pytest.raises(ErroCRS, match="ausente"):
        verificar_crs({"a": None})


# ---------------------------------------------------------------- pseudo-rótulos

def test_otsu_separa_dois_grupos():
    bordas = np.linspace(-1, 2, 301)
    v = np.concatenate([np.full(1000, 0.05), np.full(400, 0.40)])
    lim = otsu_histograma(np.histogram(v, bins=bordas)[0], bordas)
    assert 0.05 < lim <= 0.40


def test_trechos_confiaveis_exclui_vizinhos_do_duvidoso():
    linha = LineString([(0, 0), (0, 50)])
    pts = [(Point(0, 5 * k), "detectado", 0.9) for k in range(11)]  # 0, 5, ..., 50
    pts[5] = (Point(0, 25), "duvidoso", 0.9)
    cfg = ConfigMascaras(vizinhos_excluidos=1, limiar_confianca_pseudo=0.7)
    pedacos = trechos_confiaveis(linha, pts, cfg)
    # pontos 4, 5 e 6 (y 20 a 30) ficam fora; o pedaço de cada ponto vai até o meio do vizinho
    assert len(pedacos) == 2
    assert pedacos[0].bounds[3] == pytest.approx(17.5)
    assert pedacos[1].bounds[1] == pytest.approx(32.5)
    # confiança baixa também tira o ponto
    pts2 = [(p, s, 0.5 if k == 0 else c) for k, (p, s, c) in enumerate(pts)]
    assert trechos_confiaveis(linha, pts2, cfg)[0].bounds[1] == pytest.approx(7.5)


def test_regras_por_pixel():
    #           cana na faixa | verde na margem | verde fora | solo | solo escuro | fora da zona
    bandas = np.array([[60, 60, 60, 150, 20, 60],
                       [160, 160, 160, 110, 20, 160],
                       [50, 50, 50, 80, 20, 50]], dtype=np.float32).reshape(3, 1, 6)
    valido = np.ones((1, 6), dtype=bool)
    limiar = np.full((1, 6), 0.2, dtype=np.float32)
    zona = np.array([[1, 1, 1, 1, 1, 0]], dtype=bool)
    faixa = np.array([[1, 0, 0, 0, 0, 0]], dtype=bool)
    margem = np.array([[1, 1, 0, 0, 0, 0]], dtype=bool)
    # padrão (foco na cana): verde fora da faixa fica ignorado, nunca daninha
    rot = rotular_janela(bandas, valido, limiar, zona, faixa, margem, ConfigMascaras())
    assert rot.tolist() == [[CANA, IGNORADO, IGNORADO, FUNDO, FUNDO, IGNORADO]]
    rot = rotular_janela(bandas, valido, limiar, zona, faixa, margem, ConfigMascaras(daninha_por_posicao=True))
    assert rot.tolist() == [[CANA, IGNORADO, DANINHA, FUNDO, FUNDO, IGNORADO]]
    rot = rotular_janela(bandas, valido, limiar, zona, faixa, margem, ConfigMascaras(sombra_brilho_max=40))
    assert rot[0, 4] == SOMBRA


# ---------------------------------------------------------------- avaliação

def test_matriz_e_iou():
    ref = np.array([CANA, CANA, DANINHA, FUNDO, IGNORADO, SOMBRA], dtype=np.uint8)
    pred = np.array([CANA, DANINHA, DANINHA, FUNDO, CANA, IGNORADO], dtype=np.uint8)
    m = matriz_confusao(ref, pred)
    assert m.sum() == 5  # referência 0 ignorada
    assert m[0, 0] == 1 and m[0, 1] == 1 and m[3, 4] == 1  # sombra prevista como sem dado
    iou = iou_por_classe(m)
    assert iou["cana"] == pytest.approx(1 / 2)
    assert iou["daninha"] == pytest.approx(1 / 2)
    assert iou["fundo"] == 1.0 and iou["sombra"] == 0.0
