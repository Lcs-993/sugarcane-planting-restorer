"""Testes de config.py e tipos.py.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
from pathlib import Path

import pytest

from linhas_plantio.config import Config, carregar_config
from linhas_plantio.tipos import ErroConfig, ErroLinhasPlantio

RAIZ = Path(__file__).resolve().parents[1]


def test_padroes_sao_as_hipoteses_de_partida():
    cfg = carregar_config(None)
    assert cfg.indice == "exg"
    assert cfg.espacamento_estacoes_m == 10.0
    assert cfg.semijanela_busca_m == 0.50


def test_config_yaml_de_exemplo_carrega():
    assert carregar_config(RAIZ / "config.yaml") == Config()


def test_ndvi_exige_banda_nir():
    with pytest.raises(ErroConfig, match="banda_nir"):
        Config(indice="ndvi")
    assert Config(indice="ndvi", banda_nir=4).banda_nir == 4


def test_janela_mediana_par_e_erro():
    with pytest.raises(ErroConfig, match="ímpar"):
        Config(janela_mediana=4)


def test_chave_desconhecida_e_tipo_errado(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("parametro_inventado: 1\n", encoding="utf-8")
    with pytest.raises(ErroConfig, match="desconhecidos"):
        carregar_config(p)
    p.write_text("espacamento_estacoes_m: dez\n", encoding="utf-8")
    with pytest.raises(ErroConfig, match="numérico"):
        carregar_config(p)


def test_valor_fora_de_faixa_e_arquivo_ausente(tmp_path):
    with pytest.raises(ErroConfig):
        Config(espacamento_estacoes_m=0)
    with pytest.raises(ErroConfig):
        Config(fracao_duvidosa_revisao=1.5)
    with pytest.raises(ErroConfig, match="não encontrado"):
        carregar_config(tmp_path / "nao_existe.yaml")


def test_erros_herdam_da_base():
    assert issubclass(ErroConfig, ErroLinhasPlantio)
