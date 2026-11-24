"""Fluxo da máscara de classes sobre as pastas de área (dados/areas/<nome>); ver docs/guia-execucao.md, seção 5.

Só chama a linha de comando já existente (python -m mascaras); não tem lógica de segmentação.

  pseudo      <área>                      rótulos de treino a partir da última detecção sem máscara
  treinar     <modelo> <área> [<área>...] treina o classificador com os rótulos das áreas
  classificar <área> <modelo>             grava entrada/mascara/mascara.tif (usado pelo rodar_area)
  avaliar     <área>                      IoU contra os polígonos de entrada/teste_mascara

<área> é o nome de uma pasta em dados/areas (ou um caminho). <modelo> é um nome, gravado em
dados/modelos/<nome>.joblib (ou um caminho terminado em .joblib).
Pastas usadas na área, além das do rodar_area:
  entrada/correcoes_mascara  (opcional) polígonos com o campo "classe" que corrigem os pseudo-rótulos
  entrada/teste_mascara      polígonos de teste desenhados à mão, com o campo "classe" (só para avaliar)
  rotulos/                   rótulos gerados (rotulos.tif e rotulos.json); refeitos a cada "pseudo"
Configuração: config_mascaras.yaml da área, senão o da raiz; --config <arquivo> passa por cima.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from rodar_area import RAIZ, _rodar, _unico

CONFIG_PADRAO = RAIZ / "config_mascaras.yaml"
PASTA_MODELOS = RAIZ / "dados" / "modelos"
USO = __doc__.split("\n\n")[2]  # a lista de passos da docstring


def _area(nome: str) -> Path:
    p = Path(nome)
    area = p if p.is_dir() else RAIZ / "dados" / "areas" / nome
    if not area.is_dir():
        sys.exit(f"ERRO: a área {nome} não existe em dados\\areas. Crie com scripts\\nova_area.bat.")
    return area.resolve()


def _modelo(nome: str) -> Path:
    p = Path(nome)
    return p.resolve() if p.suffix == ".joblib" else PASTA_MODELOS / f"{nome}.joblib"


def _config(area: Path | None, forcada: Path | None) -> Path:
    if forcada is not None:
        if not forcada.is_file():
            sys.exit(f"ERRO: configuração {forcada} não encontrada.")
        return forcada.resolve()
    if area is not None and (area / "config_mascaras.yaml").is_file():
        return area / "config_mascaras.yaml"
    return CONFIG_PADRAO


def _pasta_execucao(area: Path, passo: str) -> Path:
    pasta = area / "saida" / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_mascaras_{passo}"
    pasta.mkdir(parents=True)
    return pasta


def _orto_talhoes(area: Path) -> tuple[Path, Path]:
    entrada = area / "entrada"
    return (_unico(entrada, ["ortomosaico"], ["*.tif", "*.tiff"], "ortomosaico", True),
            _unico(entrada, ["talhoes", "poligonos_talhoes"], ["*.shp", "*.gpkg"], "talhões", True))


def ultima_deteccao_sem_mascara(area: Path) -> Path:
    """fileiras_detectadas.gpkg da execução mais recente do rodar_area que não usou máscara
    (o pseudo-rótulo vem da detecção ExG + Otsu: docs/escopo-mascaras.md, seção 6)."""
    saida = area / "saida"
    execucoes = sorted((p for p in saida.iterdir() if (p / "fileiras_detectadas.gpkg").is_file()),
                       reverse=True) if saida.is_dir() else []
    for p in execucoes:
        log = p / "log.txt"
        if not (log.is_file() and "--mascara" in log.read_text(encoding="utf-8", errors="replace")):
            return p / "fileiras_detectadas.gpkg"
    sys.exit(f"ERRO: nenhuma detecção sem máscara em {saida}. Rode antes scripts\\rodar_area.bat "
             f"{area.name} sem arquivo em entrada\\mascara.")


def pseudo(area: Path, cfg: Path, py: str) -> int:
    orto, talhoes = _orto_talhoes(area)
    det = ultima_deteccao_sem_mascara(area)
    corr = _unico(area / "entrada", ["correcoes_mascara"], ["*.shp", "*.gpkg"], "correções manuais", False)
    saida = area / "rotulos" / "rotulos.tif"
    log = _pasta_execucao(area, "pseudo") / "log.txt"
    print(f"Área: {area.name}\n  detecção usada: {det.parent.name}\n"
          f"  correções manuais: {corr.name if corr else '(nenhuma)'}\n  config: {cfg}\n  rótulos: {saida}"
          " (refeitos a cada execução)")
    cmd = [py, "-m", "mascaras", "pseudo-rotulos", "--ortomosaico", str(orto), "--talhoes", str(talhoes),
           "--deteccao", str(det), "--saida", str(saida), "--config", str(cfg)]
    if corr:
        cmd += ["--correcoes", str(corr)]
    rc = _rodar(cmd, log)
    if rc == 0:
        print(f"\nPronto. Abra {saida} no QGIS e confira antes de treinar.")
    return rc


def treinar(modelo: Path, areas: list[Path], cfg: Path, py: str) -> int:
    cmd = [py, "-m", "mascaras", "treinar", "--modelo", str(modelo), "--config", str(cfg)]
    for area in areas:
        rot = area / "rotulos" / "rotulos.tif"
        if not rot.is_file():
            sys.exit(f"ERRO: a área {area.name} não tem rotulos\\rotulos.tif. Rode antes o passo pseudo nela.")
        cmd += ["--par", str(_orto_talhoes(area)[0]), str(rot)]
    modelo.parent.mkdir(parents=True, exist_ok=True)
    log = modelo.with_name(modelo.stem + "_log.txt")
    print(f"Modelo: {modelo}\n  áreas de treino: {', '.join(a.name for a in areas)}\n  config: {cfg}\n"
          "  Lembrete: não avalie depois em talhão que entrou no treino.")
    return _rodar(cmd, log)


def classificar(area: Path, modelo: Path, cfg: Path, py: str) -> int:
    if not modelo.is_file():
        sys.exit(f"ERRO: modelo {modelo} não encontrado. Rode antes o passo treinar.")
    orto, talhoes = _orto_talhoes(area)
    pasta = area / "entrada" / "mascara"
    pasta.mkdir(parents=True, exist_ok=True)
    saida = pasta / "mascara.tif"
    outros = [p.name for ext in ("*.tif", "*.tiff") for p in pasta.glob(ext) if p.name != saida.name]
    if outros:
        sys.exit(f"ERRO: já há outro(s) GeoTIFF em {pasta} ({', '.join(outros)}). Tire-os de lá: o rodar_area "
                 "aceita um só arquivo nessa pasta.")
    execucao = _pasta_execucao(area, "classificar")
    print(f"Área: {area.name}\n  modelo: {modelo}\n  config: {cfg}\n  máscara: {saida} (substituída se existir)")
    rc = _rodar([py, "-m", "mascaras", "classificar", "--ortomosaico", str(orto), "--talhoes", str(talhoes),
                 "--modelo", str(modelo), "--saida", str(saida), "--config", str(cfg)], execucao / "log.txt")
    prob = pasta / "mascara_prob_cana.tif"
    if prob.exists():  # fora de entrada/mascara, senão o rodar_area acharia dois GeoTIFF
        prob.replace(execucao / prob.name)
        print(f"Probabilidade da classe cana movida para {execucao / prob.name}")
    if rc == 0:
        print(f"\nPronto. Agora rode scripts\\rodar_area.bat {area.name}: a detecção vai usar a máscara.")
    return rc


def avaliar(area: Path, py: str) -> int:
    entrada = area / "entrada"
    mascara = _unico(entrada, ["mascara"], ["*.tif", "*.tiff"], "máscara de classes", True)
    teste = _unico(entrada, ["teste_mascara"], ["*.shp", "*.gpkg"], "polígonos de teste", True)
    execucao = _pasta_execucao(area, "avaliar")
    print(f"Área: {area.name}\n  máscara: {mascara.name}\n  teste: {teste.name}\n"
          "  Lembrete: o teste é desenhado à mão, num talhão fora do treino; pseudo-rótulo não serve.")
    return _rodar([py, "-m", "mascaras", "avaliar", "--mascara", str(mascara), "--teste", str(teste),
                   "--relatorio", str(execucao / "relatorio_iou.json")], execucao / "log.txt")


def main(argv: list[str]) -> int:
    for fluxo in (sys.stdout, sys.stderr):  # mensagens com acento, também as de erro (sys.exit)
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    args = list(argv[1:])
    forcada = None
    if "--config" in args:
        i = args.index("--config")
        if i + 1 >= len(args):
            sys.exit("ERRO: --config sem arquivo.")
        forcada = Path(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit("uso: python scripts/mascaras_area.py <passo> ...\n" + USO)
    passo, resto = args[0], args[1:]
    py = sys.executable
    if passo == "pseudo" and len(resto) == 1:
        area = _area(resto[0])
        return pseudo(area, _config(area, forcada), py)
    if passo == "treinar" and len(resto) >= 2:
        return treinar(_modelo(resto[0]), [_area(a) for a in resto[1:]], _config(None, forcada), py)
    if passo == "classificar" and len(resto) == 2:
        area = _area(resto[0])
        return classificar(area, _modelo(resto[1]), _config(area, forcada), py)
    if passo == "avaliar" and len(resto) == 1:
        return avaliar(_area(resto[0]), py)
    sys.exit("uso: python scripts/mascaras_area.py <passo> ...\n" + USO)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
