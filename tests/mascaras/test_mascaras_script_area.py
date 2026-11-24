"""Teste do script scripts/mascaras_area.py (os quatro passos sobre uma pasta de área).

AVISO: imagem sintética; prova o fluxo, não a acurácia.
"""
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from sinteticos_mascaras import CRS_M, ORIGEM, centros_fileiras, gerar_deteccao, gerar_orto, gerar_talhao, manchas_daninha

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "mascaras_area.py"


def _area(tmp_path, nome="area_x"):
    area = tmp_path / nome
    for d in ["entrada/ortomosaico", "entrada/talhoes", "saida"]:
        (area / d).mkdir(parents=True)
    gerar_orto(area / "entrada/ortomosaico/o.tif", daninhas=manchas_daninha(30, 30, n=15))
    gerar_talhao(area / "entrada/talhoes/t.gpkg")
    sem = area / "saida/2026-01-01_000000"
    sem.mkdir()
    gerar_deteccao(sem / "fileiras_detectadas.gpkg")
    (sem / "log.txt").write_text("> python -m deteccao_linhas detectar ...\n", encoding="utf-8")
    com = area / "saida/2026-01-02_000000"  # mais recente, mas com máscara: não serve para pseudo-rótulo
    com.mkdir()
    gpd.GeoDataFrame({"x": [1]}, geometry=[box(0, 0, 1, 1)], crs=CRS_M).to_file(
        com / "fileiras_detectadas.gpkg", driver="GPKG")
    (com / "log.txt").write_text("> python -m deteccao_linhas detectar ... --mascara m.tif\n", encoding="utf-8")
    return area


def _cfg(tmp_path):
    c = tmp_path / "cfg.yaml"
    c.write_text("buffer_interno_m: 1.0\nn_arvores: 10\nmax_amostras_por_classe: 2000\nn_jobs: 1\n"
                 "gravar_probabilidade_cana: true\n", encoding="utf-8")
    return c


def _rodar(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=RAIZ)


def test_quatro_passos(tmp_path):
    area, cfg = _area(tmp_path), _cfg(tmp_path)
    corr = area / "entrada/correcoes_mascara"
    corr.mkdir()
    x = ORIGEM[0] + centros_fileiras(30)[2]
    gpd.GeoDataFrame({"classe": ["daninha"]}, geometry=[box(x - 0.3, ORIGEM[1] - 6, x + 0.3, ORIGEM[1] - 5)],
                     crs=CRS_M).to_file(corr / "c.gpkg", driver="GPKG")

    r = _rodar("pseudo", area, "--config", cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2026-01-01_000000" in r.stdout and "c.gpkg" in r.stdout
    assert (area / "rotulos/rotulos.tif").exists() and (area / "rotulos/rotulos.json").exists()

    modelo = tmp_path / "modelos/m1.joblib"
    r = _rodar("treinar", modelo, area, "--config", cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert modelo.exists() and (tmp_path / "modelos/m1_log.txt").exists()

    r = _rodar("classificar", area, modelo, "--config", cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    tifs = sorted(p.name for p in (area / "entrada/mascara").glob("*.tif"))
    assert tifs == ["mascara.tif"]  # a probabilidade sai da pasta, que o rodar_area exige com um arquivo só
    assert list((area / "saida").glob("*_mascaras_classificar/mascara_prob_cana.tif"))

    teste = area / "entrada/teste_mascara"
    teste.mkdir()
    x = ORIGEM[0] + centros_fileiras(30)[5]
    gpd.GeoDataFrame({"classe": [1]}, geometry=[box(x - 0.15, ORIGEM[1] - 20, x + 0.15, ORIGEM[1] - 10)],
                     crs=CRS_M).to_file(teste / "t.gpkg", driver="GPKG")
    r = _rodar("avaliar", area)
    assert r.returncode == 0, r.stdout + r.stderr
    assert list((area / "saida").glob("*_mascaras_avaliar/relatorio_iou.json"))


def test_erros_claros(tmp_path):
    area, cfg = _area(tmp_path), _cfg(tmp_path)
    r = _rodar("treinar", tmp_path / "m.joblib", area, "--config", cfg)
    assert r.returncode != 0 and "pseudo" in r.stderr  # sem rótulos ainda
    r = _rodar("classificar", area, tmp_path / "nao.joblib")
    assert r.returncode != 0 and "não encontrado" in r.stderr
    r = _rodar("pseudo", tmp_path / "nao_existe")
    assert r.returncode != 0 and "não existe" in r.stderr
    r = _rodar("passo_errado", area)
    assert r.returncode != 0 and "uso:" in r.stderr
    for p in (area / "saida").iterdir():
        if (p / "log.txt").exists():
            (p / "log.txt").write_text("--mascara\n", encoding="utf-8")
    r = _rodar("pseudo", area, "--config", cfg)
    assert r.returncode != 0 and "nenhuma detecção sem máscara" in r.stderr
