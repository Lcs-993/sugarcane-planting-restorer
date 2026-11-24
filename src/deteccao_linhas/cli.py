"""Linha de comando e orquestração (docs/interfaces-deteccao.md, seção 6.10).

Sem lógica de geometria própria. executar_deteccao é o ponto de integração futuro do plugin QGIS.
A detecção nunca lê camada de linhas: não há parâmetro para isso.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .comparacao import RelatorioComparacao, comparar, gravar_diferencas
from .config import Config, ConfigComparacao, carregar_config, carregar_config_comparacao
from .entrada import carregar_entrada
from .fonte_mascara import abrir_fonte_mascara, abrir_raster_mascara
from .indice_binarizacao import (abrir_fonte_binaria, abrir_fonte_indice, calcular_limiar_otsu,
                                 recortar_talhao)
from .orientacao import dividir_em_regioes, estimar_campo_direcao, estimar_direcoes
from .pente import ajustar_bloco
from .perfil_lateral import calcular_perfil, gerar_blocos, gerar_blocos_faixas
from .qualidade import avaliar_trilhas
from .rastreamento import rastrear_com_descartes
from .saida import gravar_geopackage, numerar_fileiras
from .tipos import STATUS_VALIDOS, ErroDeteccao, ErroDeteccaoLinhas, Fileira, ResumoDeteccao

PASSO_PROGRESSO = 25  # blocos entre mensagens de progresso


def executar_deteccao(caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_saida: Path,
                      cfg: Config) -> list[ResumoDeteccao]:
    """Orquestra o fluxo da seção 5 talhão a talhão e grava o GeoPackage.

    Com cfg.perfil_sobre == "mascara", a fonte do perfil é a máscara de classes (só a classe cana conta
    como vegetação) e não há limiar de Otsu (limiar_otsu = NaN no resumo). O resto do fluxo não muda.
    """
    dados = carregar_entrada(caminho_ortomosaico, caminho_talhoes, cfg)
    usa_mascara = cfg.perfil_sobre == "mascara"
    fonte = None if usa_mascara else abrir_fonte_indice(dados.caminho_ortomosaico, cfg)
    raster_mascara = (abrir_raster_mascara(Path(cfg.caminho_mascara), dados.crs, cfg.resolucao_trabalho_m)
                      if usa_mascara else None)
    resumos: list[ResumoDeteccao] = []
    todas: list[Fileira] = []
    try:
        for talhao in dados.talhoes:
            area = recortar_talhao(talhao, cfg)
            if usa_mascara:
                limiar = float("nan")
                fb = abrir_fonte_mascara(raster_mascara, area, cfg.resolucao_trabalho_m)
                print(f"[{talhao.id}] perfil sobre a máscara de classes; orientação por região...", flush=True)
            else:
                print(f"[{talhao.id}] área útil e limiar de Otsu...", flush=True)
                limiar = calcular_limiar_otsu(fonte, area, cfg)
                fb = abrir_fonte_binaria(fonte, area, limiar, cfg)
                print(f"[{talhao.id}] limiar={limiar:.4f}; orientação por região...", flush=True)
            c = area.poligono_util.centroid
            if cfg.modo_blocos == "faixas":
                campo, regioes, u_ref = estimar_campo_direcao(fb, area, cfg)
                blocos = gerar_blocos_faixas(campo, area.poligono_util, u_ref, (c.x, c.y), cfg)
            else:
                regioes, u_ref = estimar_direcoes(fb, dividir_em_regioes(area, cfg), cfg)
                blocos = gerar_blocos(regioes, u_ref, (c.x, c.y), cfg)
            herdadas = sum(r.direcao.herdada for r in regioes)
            print(f"[{talhao.id}] {len(regioes)} regiões ({herdadas} com direção herdada), {len(blocos)} blocos",
                  flush=True)
            resultados = []
            for k, b in enumerate(blocos, start=1):
                resultados.append(ajustar_bloco(calcular_perfil(fb, b, cfg), cfg))
                if k % PASSO_PROGRESSO == 0:
                    print(f"[{talhao.id}] blocos {k}/{len(blocos)}", flush=True)
            trilhas, descartadas = rastrear_com_descartes(resultados, cfg)
            avaliadas = avaliar_trilhas(trilhas, talhao.id, cfg)
            if not avaliadas:
                raise ErroDeteccao(f"talhão {talhao.id!r}: nenhuma fileira detectada")
            fileiras = numerar_fileiras(avaliadas, u_ref, (c.x, c.y))
            todas.extend(fileiras)
            contagem = {s: 0 for s in STATUS_VALIDOS}
            for f in fileiras:
                for p in f.avaliada.pontos:
                    contagem[p.status] += 1
            resumos.append(ResumoDeteccao(
                talhao=talhao.id, limiar_otsu=limiar, n_regioes=len(regioes), n_regioes_direcao_herdada=herdadas,
                n_blocos=len(blocos), n_fileiras=len(fileiras), n_trilhas_descartadas=descartadas,
                n_pontos_por_status=contagem))
            print(f"[{talhao.id}] {len(fileiras)} fileiras; pontos {contagem}; "
                  f"{descartadas} trilhas descartadas por comprimento", flush=True)
    finally:
        if fonte is not None:
            fonte.fechar()
        if raster_mascara is not None:
            raster_mascara.fechar()
    gravar_geopackage(todas, dados.crs, caminho_saida)
    return resumos


def executar_comparacao(caminho_fileiras: Path, caminho_referencia: Path,
                        cfg: ConfigComparacao) -> RelatorioComparacao:
    """Chama comparacao.comparar. A detecção nunca é chamada daqui."""
    return comparar(caminho_fileiras, caminho_referencia, cfg)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m deteccao_linhas",
                                description="Detecção de linhas de plantio a partir só do ortomosaico e do talhão.")
    sub = p.add_subparsers(dest="comando", required=True)
    d = sub.add_parser("detectar", help="detecta as fileiras e grava o GeoPackage")
    d.add_argument("--ortomosaico", required=True, type=Path)
    d.add_argument("--talhoes", required=True, type=Path)
    d.add_argument("--saida", required=True, type=Path)
    d.add_argument("--config", type=Path, default=None)
    d.add_argument("--mascara", type=Path, default=None,
                   help="GeoTIFF de classes (python -m mascaras classificar); liga perfil_sobre=mascara")
    c = sub.add_parser("comparar", help="compara as fileiras detectadas com uma referência secundária")
    c.add_argument("--fileiras", required=True, type=Path)
    c.add_argument("--referencia", required=True, type=Path)
    c.add_argument("--config", type=Path, default=None)
    c.add_argument("--relatorio", type=Path, default=None, help="grava o relatório em JSON")
    c.add_argument("--saida-diferencas", type=Path, default=None)
    return p


def _fmt(e) -> str:
    f = lambda v: "-" if v is None else f"{v:.3f}"  # noqa: E731
    return f"n={e.n} média|d|={f(e.media_abs_m)} mediana|d|={f(e.mediana_abs_m)} p95|d|={f(e.p95_abs_m)} viés={f(e.vies_m)}"


def main(argv: list[str] | None = None) -> int:
    """Códigos de saída: 0 sucesso; 2 erro de contrato (ErroDeteccaoLinhas); 1 erro inesperado."""
    args = _parser().parse_args(argv)
    try:
        if args.comando == "detectar":
            cfg = carregar_config(args.config)
            if args.mascara is not None:
                cfg = replace(cfg, perfil_sobre="mascara", caminho_mascara=str(args.mascara))
            resumos = executar_deteccao(args.ortomosaico, args.talhoes, args.saida, cfg)
            print(f"Fileiras gravadas em {args.saida}")
            for r in resumos:
                print(f"  {r.talhao}: {r.n_fileiras} fileiras, pontos {r.n_pontos_por_status}")
        else:
            cfg_c = carregar_config_comparacao(args.config)
            rel = executar_comparacao(args.fileiras, args.referencia, cfg_c)
            print(rel.aviso)
            print(f"trechos={rel.n_trechos}  pareamento={rel.taxa_pareamento:.1%}  "
                  f"cobertura da referência={rel.cobertura_referencia:.1%}")
            print("global:", _fmt(rel.global_))
            for s, e in rel.por_status.items():
                print(f"  {s}:", _fmt(e))
            if args.relatorio:
                args.relatorio.write_text(json.dumps(asdict(rel), ensure_ascii=False, indent=2), encoding="utf-8")
            if args.saida_diferencas:
                gravar_diferencas(args.fileiras, args.referencia, cfg_c, args.saida_diferencas)
        return 0
    except ErroDeteccaoLinhas as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Erro inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
