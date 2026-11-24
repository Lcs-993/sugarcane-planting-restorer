"""Roda a detecção de fileiras numa área de dados (pasta em dados/areas/<nome>).

Só chama a linha de comando já existente (python -m deteccao_linhas); não tem lógica de detecção.
Convenção de pastas (ver docs/guia-execucao.md):
  entrada/ortomosaico  um GeoTIFF RGB
  entrada/talhoes      (ou entrada/poligonos_talhoes) um .shp ou .gpkg com os polígonos; o campo
                       identificador é "id", ou o que o config.yaml da área indicar em campo_id_talhao
  entrada/referencia   (ou entrada/linhas_fileiras_cana_projetadas) (opcional) um .shp ou .gpkg com
                       linhas de referência, para comparar
  entrada/linhas_mae, entrada/linhas_piloto_automatico_plantio  guardadas para o teste de linhas
                       gêmeas (ainda não lidas)
  entrada/mascara      (opcional) um GeoTIFF de classes (python -m mascaras classificar); se existir,
                       o perfil das fileiras usa a classe cana dele em vez do ExG + Otsu
  config.yaml          (opcional) configuração da detecção da área; senão usa config_deteccao.yaml
  config_comparacao.yaml (opcional) configuração da comparação
  entrada/mds, entrada/mdt  reservadas para o teste opcional do modelo de terreno (ainda não lidas)
  saida/               cada execução cria uma subpasta com data e hora; nada é sobrescrito
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "config_deteccao.yaml"


def _unico(entrada: Path, pastas: list[str], padroes: list[str], rotulo: str, obrigatorio: bool) -> Path | None:
    """Procura o arquivo na primeira pasta que existir, na ordem de `pastas` (nomes alternativos)."""
    pasta = next((entrada / n for n in pastas if (entrada / n).is_dir()), entrada / pastas[0])
    achados = sorted(p for padrao in padroes for p in pasta.glob(padrao) if p.is_file())
    if not achados:
        if obrigatorio:
            sys.exit(f"ERRO: nenhum arquivo de {rotulo} em {pasta}. Coloque o arquivo nessa pasta.")
        return None
    if len(achados) > 1:
        nomes = ", ".join(p.name for p in achados)
        sys.exit(f"ERRO: mais de um arquivo de {rotulo} em {pasta} ({nomes}). Deixe só um.")
    return achados[0]


def _rodar(args: list[str], log: Path) -> int:
    print("\n>", " ".join(args), flush=True)
    with log.open("a", encoding="utf-8") as f:
        f.write("\n> " + " ".join(args) + "\n")
        # o filho escreve em UTF-8 (acentos das mensagens), como este processo lê
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env)
        assert proc.stdout is not None
        for linha in proc.stdout:
            print(linha, end="", flush=True)
            f.write(linha)
        return proc.wait()


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2:
        sys.exit("uso: python scripts/rodar_area.py dados/areas/<nome_da_area>")
    area = Path(argv[1]).resolve()
    if not area.is_dir():
        sys.exit(f"ERRO: a pasta {area} não existe. Crie a área com scripts\\nova_area.bat.")
    entrada = area / "entrada"
    orto = _unico(entrada, ["ortomosaico"], ["*.tif", "*.tiff"], "ortomosaico", True)
    talhoes = _unico(entrada, ["talhoes", "poligonos_talhoes"], ["*.shp", "*.gpkg"], "talhões", True)
    ref = _unico(entrada, ["referencia", "linhas_fileiras_cana_projetadas"], ["*.shp", "*.gpkg"], "referência", False)
    mascara = _unico(entrada, ["mascara"], ["*.tif", "*.tiff"], "máscara de classes", False)
    config = area / "config.yaml"
    if not config.exists():
        config = CONFIG_PADRAO

    saida = area / "saida" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    saida.mkdir(parents=True)
    log = saida / "log.txt"
    print(f"Área: {area.name}\n  ortomosaico: {orto.name}\n  talhões: {talhoes.name}\n"
          f"  referência: {ref.name if ref else '(nenhuma, não vai comparar)'}\n"
          f"  máscara de classes: {mascara.name if mascara else '(nenhuma, perfil sobre ExG + Otsu)'}\n"
          f"  config: {config}\n  saída: {saida}")

    fileiras = saida / "fileiras_detectadas.gpkg"
    py = sys.executable
    cmd = [py, "-m", "deteccao_linhas", "detectar", "--ortomosaico", str(orto),
           "--talhoes", str(talhoes), "--saida", str(fileiras), "--config", str(config)]
    if mascara:
        cmd += ["--mascara", str(mascara)]
    rc = _rodar(cmd, log)
    if rc != 0:
        print(f"\nA detecção terminou com erro (código {rc}). Veja a mensagem acima e {log}.")
        return rc
    if ref:
        # A comparação tem configuração própria (ConfigComparacao): só é passada se existir na área.
        cmd = [py, "-m", "deteccao_linhas", "comparar", "--fileiras", str(fileiras), "--referencia", str(ref),
               "--relatorio", str(saida / "relatorio_comparacao.json"),
               "--saida-diferencas", str(saida / "diferencas.gpkg")]
        if (area / "config_comparacao.yaml").exists():
            cmd += ["--config", str(area / "config_comparacao.yaml")]
        rc = _rodar(cmd, log)
        if rc != 0:
            print(f"\nA comparação terminou com erro (código {rc}). Veja {log}.")
            return rc
        print("\nLembrete: a comparação usa uma referência secundária, não é RTK; não mede acurácia.")
    print(f"\nPronto. Resultados em: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
