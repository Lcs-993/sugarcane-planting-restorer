"""Teste do script scripts/rodar_area.py (executa a linha de comando numa pasta de área).

AVISO: testes sintéticos mostram que o fluxo funciona, não a acurácia em campo.
"""
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from conftest import gerar_fileiras, gerar_talhao

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "rodar_area.py"
ORIGEM = (394000.0, 7775000.0)


def _area(tmp_path, com_ref=True):
    area = tmp_path / "area_x"
    for d in ["entrada/ortomosaico", "entrada/talhoes", "entrada/referencia", "saida"]:
        (area / d).mkdir(parents=True)
    gerar_fileiras(area / "entrada/ortomosaico/o.tif", largura_m=60, altura_m=60, angulo_graus=0.0,
                   fase_m=0.3, origem=ORIGEM, ruido=4.0)
    gerar_talhao(area / "entrada/talhoes/t.gpkg", (ORIGEM[0], ORIGEM[1] - 60, ORIGEM[0] + 60, ORIGEM[1]))
    (area / "config.yaml").write_text("regiao_m: 50\narea_minima_regiao_m2: 500\ncomprimento_min_fileira_m: 20\n")
    if com_ref:
        linhas = [LineString([(ORIGEM[0] + 0.3 + 1.5 * k, ORIGEM[1] - 70), (ORIGEM[0] + 0.3 + 1.5 * k, ORIGEM[1] + 10)])
                  for k in range(0, 40)]
        gpd.GeoDataFrame({"id": range(len(linhas))}, geometry=linhas, crs="EPSG:31983").to_file(
            area / "entrada/referencia/r.gpkg", driver="GPKG")
    return area


def _rodar(area):
    return subprocess.run([sys.executable, str(SCRIPT), str(area)], capture_output=True, text=True,
                          encoding="utf-8", cwd=RAIZ)


def test_rodar_area_com_referencia(tmp_path):
    area = _area(tmp_path)
    r = _rodar(area)
    assert r.returncode == 0, r.stdout + r.stderr
    exec_ = [p for p in (area / "saida").iterdir() if p.is_dir()]
    assert len(exec_) == 1
    for nome in ["fileiras_detectadas.gpkg", "relatorio_comparacao.json", "diferencas.gpkg", "log.txt"]:
        assert (exec_[0] / nome).exists(), nome
    assert "não é RTK" in r.stdout


def test_rodar_area_sem_referencia_nao_compara(tmp_path):
    area = _area(tmp_path, com_ref=False)
    r = _rodar(area)
    assert r.returncode == 0, r.stdout + r.stderr
    exec_ = [p for p in (area / "saida").iterdir() if p.is_dir()][0]
    assert (exec_ / "fileiras_detectadas.gpkg").exists()
    assert not (exec_ / "relatorio_comparacao.json").exists()


def test_rodar_area_mensagem_clara_sem_ortomosaico(tmp_path):
    area = _area(tmp_path)
    (area / "entrada/ortomosaico/o.tif").unlink()
    r = _rodar(area)
    assert r.returncode != 0
    assert "nenhum arquivo de ortomosaico" in (r.stdout + r.stderr)
