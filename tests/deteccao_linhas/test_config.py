import pytest

from deteccao_linhas.config import (Config, ConfigComparacao, carregar_config,
                                    carregar_config_comparacao)
from deteccao_linhas.tipos import ErroConfig


def test_padroes_validos():
    c = Config()
    assert c.espacamento_fileiras_ref_m == 1.5
    assert sum(c.pesos_confianca) == pytest.approx(1.0)
    assert ConfigComparacao().distancia_max_pareamento_m == 0.5


def test_none_devolve_padrao():
    assert carregar_config(None) == Config()
    assert carregar_config_comparacao(None) == ConfigComparacao()


def test_yaml_exemplo_carrega():
    from pathlib import Path
    c = carregar_config(Path(__file__).parents[2] / "config_deteccao.yaml")
    assert c == Config()


def test_yaml_sobrescreve(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("comprimento_bloco_m: 20\npasso_bloco_m: 10\npesos_confianca: [0.4, 0.2, 0.2, 0.2]\n")
    c = carregar_config(p)
    assert c.comprimento_bloco_m == 20.0 and c.pesos_confianca == (0.4, 0.2, 0.2, 0.2)


@pytest.mark.parametrize("txt", [
    "chave_inexistente: 1",
    "sg_janela: 10",
    "janela_mediana: 2",
    "passo_bloco_m: 20",
    "resolucao_trabalho_m: 0",
    "pesos_confianca: [0.5, 0.5, 0.5, 0.5]",
    "largura_faixa_min_m: 0.6",
    "sg_janela: abc",
    "perfil_sobre: indice",
])
def test_yaml_invalido(tmp_path, txt):
    p = tmp_path / "c.yaml"
    p.write_text(txt + "\n")
    with pytest.raises(ErroConfig):
        carregar_config(p)


def test_arquivo_ausente(tmp_path):
    with pytest.raises(ErroConfig):
        carregar_config(tmp_path / "nao.yaml")


def test_comparacao_invalida(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("usar_status: [foo]\n")
    with pytest.raises(ErroConfig):
        carregar_config_comparacao(p)
