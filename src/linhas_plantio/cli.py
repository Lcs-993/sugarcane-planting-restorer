"""Linha de comando: python -m linhas_plantio corrigir --ortomosaico X --talhoes Y --linhas Z
--saida W --config C (docs/interfaces-fase1.md, seção 7). Sem lógica de geometria própria."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from .config import Config, carregar_config
from .deteccao import detectar_passada
from .desvio import calcular_desvios
from .entrada import carregar_entrada
from .preprocessamento import abrir_fonte_indice, recortar_talhao
from .qualidade import avaliar_passada
from .reconstrucao import reconstruir_passada
from .saida import gravar_geopackage
from .segmentacao import abrir_fonte_binaria, calcular_limiar_otsu
from .tipos import ErroLinhasPlantio, ResultadoPassada


def executar_correcao(
    caminho_ortomosaico: Path,
    caminho_talhoes: Path,
    caminho_linhas: Path,
    caminho_saida: Path,
    cfg: Config,
    progresso: Callable[[str], None] | None = None,
) -> list[ResultadoPassada]:
    """Orquestra o fluxo talhão a talhão (docs/interfaces-fase1.md, seção 5). Sem lógica de
    geometria própria. `progresso` recebe uma mensagem por talhão e por passada."""
    avisar = progresso or (lambda _msg: None)
    dados = carregar_entrada(caminho_ortomosaico, caminho_talhoes, caminho_linhas, cfg)
    resultados: list[ResultadoPassada] = []
    with abrir_fonte_indice(dados.caminho_ortomosaico, cfg) as fonte:
        for talhao in dados.talhoes:
            passadas = [p for p in dados.passadas if p.talhao == talhao.id]
            if not passadas:
                avisar(f"talhão {talhao.id}: sem passadas, ignorado")
                continue
            avisar(f"talhão {talhao.id}: {len(passadas)} passada(s)")
            area = recortar_talhao(talhao, cfg)
            fonte_bin = abrir_fonte_binaria(fonte, area, calcular_limiar_otsu(fonte, area))
            for i, passada in enumerate(passadas, start=1):
                deteccoes = detectar_passada(passada, fonte_bin, cfg)
                estacoes = avaliar_passada(calcular_desvios(passada, deteccoes, cfg), cfg)
                resultados.append(reconstruir_passada(passada, estacoes, cfg))
                avisar(f"talhão {talhao.id}: passada {passada.id_passada} ({i}/{len(passadas)})")
    gravar_geopackage(resultados, dados.crs, caminho_saida)
    return resultados


def _resumo(resultados: list[ResultadoPassada]) -> str:
    status = Counter(e.status for r in resultados for e in r.estacoes)
    revisao = [r.passada.id_passada for r in resultados if r.revisao_manual]
    linhas = [
        f"passadas: {len(resultados)}",
        "estações por status: " + ", ".join(f"{k}={status.get(k, 0)}" for k in ("detectado", "estimado", "interpolado", "duvidoso")),
        f"passadas para revisão manual: {len(revisao)}" + (f" ({', '.join(revisao)})" if revisao else ""),
    ]
    return "\n".join(linhas)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="linhas_plantio", description="Correção de linhas de piloto de plantio de cana.")
    sub = p.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("corrigir", help="reposiciona as linhas de piloto a partir do ortomosaico")
    c.add_argument("--ortomosaico", required=True, type=Path, help="GeoTIFF RGB")
    c.add_argument("--talhoes", required=True, type=Path, help="polígonos dos talhões (.gpkg ou .shp)")
    c.add_argument("--linhas", required=True, type=Path, help="linhas de piloto projetadas (.gpkg ou .shp)")
    c.add_argument("--saida", required=True, type=Path, help="GeoPackage de saída")
    c.add_argument("--config", type=Path, default=None, help="YAML de configuração (opcional)")
    return p


def main(argv: list[str] | None = None) -> int:
    """Subcomando 'corrigir'. --config é opcional (sem ele, usa os padrões). Imprime progresso por
    talhão e o resumo final. Códigos de saída: 0 sucesso; 2 erro de contrato (mensagem no stderr);
    1 erro inesperado."""
    args = _parser().parse_args(argv)
    try:
        cfg = carregar_config(args.config)
        resultados = executar_correcao(
            args.ortomosaico, args.talhoes, args.linhas, args.saida, cfg,
            progresso=lambda m: print(m, flush=True),
        )
        print(_resumo(resultados))
        print(f"saída gravada em {args.saida}")
        return 0
    except ErroLinhasPlantio as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # erro inesperado
        print(f"erro inesperado ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
