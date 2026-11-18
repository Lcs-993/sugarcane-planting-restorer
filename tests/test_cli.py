"""Testes da linha de comando.

AVISO: testes sintéticos mostram que o algoritmo funciona, não a acurácia em campo.
A acurácia só se mede com referência RTK, conforme docs/plano-validacao.md.
"""
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pytest

import sinteticos as syn
from linhas_plantio.cli import main

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def caso(tmp_path_factory):
    return syn.gerar_caso(tmp_path_factory.mktemp("cli"), syn.deriva_constante(0.2))


def _args(caso, saida, config=None):
    a = ["corrigir", "--ortomosaico", str(caso.raster), "--talhoes", str(caso.talhoes),
         "--linhas", str(caso.linhas), "--saida", str(saida)]
    return a + (["--config", str(config)] if config else [])


def test_main_sucesso_imprime_progresso_e_resumo(caso, tmp_path, capsys):
    saida = tmp_path / "s.gpkg"
    assert main(_args(caso, saida, RAIZ / "config.yaml")) == 0
    out = capsys.readouterr().out
    assert "talhão T1: 7 passada(s)" in out and "passadas: 7" in out and "estações por status:" in out
    assert len(gpd.read_file(saida, layer="estacoes")) == 63


def test_main_sem_config_usa_padroes(caso, tmp_path):
    assert main(_args(caso, tmp_path / "s.gpkg")) == 0


def test_erro_de_contrato_devolve_2_com_mensagem_clara(tmp_path, capsys):
    c = syn.gerar_caso(tmp_path / "d", syn.deriva_constante(), lacunas=[], crs_talhoes="EPSG:4674")
    assert main(_args(c, tmp_path / "s.gpkg")) == 2
    err = capsys.readouterr().err
    assert "CRS divergente" in err and "Divergem do ortomosaico: talhoes" in err
    assert not (tmp_path / "s.gpkg").exists()


def test_config_invalida_devolve_2(caso, tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("indice: ndvi\n", encoding="utf-8")
    assert main(_args(caso, tmp_path / "s.gpkg", cfg)) == 2
    assert "banda_nir" in capsys.readouterr().err


def test_python_m_linhas_plantio(caso, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(RAIZ / "src"))
    r = subprocess.run([sys.executable, "-m", "linhas_plantio"] + _args(caso, tmp_path / "s.gpkg"),
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "saída gravada em" in r.stdout
