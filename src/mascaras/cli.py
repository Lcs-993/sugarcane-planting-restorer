"""Linha de comando do pacote de máscaras. Sem lógica própria: só chama os módulos.

Fluxo (docs/escopo-mascaras.md):
  1. python -m deteccao_linhas detectar ...              (detecção atual, ExG + Otsu)
  2. python -m mascaras pseudo-rotulos ...               (rótulos a partir dos trechos confiáveis)
  3. python -m mascaras treinar --par orto.tif rot.tif   (uma vez, com vários talhões)
  4. python -m mascaras classificar ...                  (máscara de classes de um ortomosaico)
  5. python -m deteccao_linhas detectar ... --mascara mascara.tif
  6. python -m mascaras avaliar ...                      (opcional: contra polígonos de teste manuais)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .avaliacao import avaliar
from .config import carregar_config
from .inferencia import classificar
from .objetos_modelo import AreaObjetos, classificar_objetos, treinar_objetos
from .pseudo_rotulos import gerar_pseudo_rotulos
from .tipos import ErroMascaras
from .treino import ParTreino, treinar


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m mascaras",
                                description="Máscara de classes (cana, daninha, fundo, sombra) do ortomosaico.")
    sub = p.add_subparsers(dest="comando", required=True)

    r = sub.add_parser("pseudo-rotulos", help="gera rótulos de treino a partir de uma execução da detecção")
    r.add_argument("--ortomosaico", required=True, type=Path)
    r.add_argument("--talhoes", required=True, type=Path)
    r.add_argument("--deteccao", required=True, type=Path, help="fileiras_detectadas.gpkg da detecção")
    r.add_argument("--correcoes", type=Path, default=None, help="polígonos manuais com o campo 'classe'")
    r.add_argument("--saida", required=True, type=Path, help="GeoTIFF de rótulos")
    r.add_argument("--config", type=Path, default=None)

    t = sub.add_parser("treinar", help="treina o classificador por pixel (nível 1)")
    t.add_argument("--par", nargs=2, action="append", required=True, metavar=("ORTOMOSAICO", "ROTULOS"),
                   type=Path, help="repita para cada talhão ou área de treino")
    t.add_argument("--modelo", required=True, type=Path, help="arquivo .joblib (o .json vai ao lado)")
    t.add_argument("--config", type=Path, default=None)

    c = sub.add_parser("classificar", help="gera a máscara de classes de um ortomosaico")
    c.add_argument("--ortomosaico", required=True, type=Path)
    c.add_argument("--talhoes", required=True, type=Path)
    c.add_argument("--modelo", required=True, type=Path)
    c.add_argument("--saida", required=True, type=Path)
    c.add_argument("--config", type=Path, default=None)

    ot = sub.add_parser("objetos-treinar",
                        help="etapa 2: treina cana x daninha por superpixel com amostras pontuais")
    ot.add_argument("--area", nargs=4, action="append", required=True, type=str,
                    metavar=("ORTOMOSAICO", "TALHOES", "DETECCAO", "AMOSTRAS"),
                    help="repita por área; DETECCAO = fileiras_detectadas.gpkg ou '-' (só com usar_posicao: false)")
    ot.add_argument("--modelo", required=True, type=Path)
    ot.add_argument("--config", type=Path, default=None)

    oc = sub.add_parser("objetos-classificar", help="etapa 2: grava a máscara cana x daninha x fundo")
    oc.add_argument("--ortomosaico", required=True, type=Path)
    oc.add_argument("--talhoes", required=True, type=Path)
    oc.add_argument("--deteccao", type=Path, default=None, help="obrigatório se o modelo usa posição")
    oc.add_argument("--modelo", required=True, type=Path)
    oc.add_argument("--saida", required=True, type=Path)
    oc.add_argument("--config", type=Path, default=None)

    a = sub.add_parser("avaliar", help="IoU e matriz de confusão contra polígonos de teste manuais")
    a.add_argument("--mascara", required=True, type=Path)
    a.add_argument("--teste", required=True, type=Path, help="polígonos revisados com o campo 'classe'")
    a.add_argument("--relatorio", type=Path, default=None, help="grava o relatório em JSON")
    return p


def _imprimir_validacao(validacao: dict) -> None:
    print("Validação deixando um talhão de fora (o modelo nunca vê o talhão testado):")
    for variante, res in validacao.items():
        g = res.get("global")
        if g is None:
            print(f"  {variante}: sem talhão testável ({res['pulados']})")
            continue
        print(f"  {variante}: n={g['n']} acerto cana={g['acerto_cana']} acerto daninha={g['acerto_daninha']} "
              f"acurácia={g['acuracia']}")
        for t, r in res["por_talhao"].items():
            print(f"    {t}: n={r['n']} cana={r['acerto_cana']} daninha={r['acerto_daninha']}")
        for t, motivo in res["pulados"].items():
            print(f"    {t}: pulado ({motivo})")


def main(argv: list[str] | None = None) -> int:
    """Códigos de saída: 0 sucesso; 2 erro de contrato (ErroMascaras); 1 erro inesperado."""
    args = _parser().parse_args(argv)
    try:
        if args.comando == "pseudo-rotulos":
            cfg = carregar_config(args.config)
            res = gerar_pseudo_rotulos(args.ortomosaico, args.talhoes, args.deteccao, args.saida, cfg,
                                       args.correcoes)
            print(f"Rótulos gravados em {args.saida}")
            print(f"  trecho confiável: {res.comprimento_confiavel_m:.0f} m de {res.comprimento_total_m:.0f} m")
            print(f"  pixels por classe: {res.pixels_por_classe}")
            print(f"  {res.aviso}")
        elif args.comando == "treinar":
            cfg = carregar_config(args.config)
            meta = treinar([ParTreino(o, r) for o, r in args.par], args.modelo, cfg)
            print(f"Modelo gravado em {args.modelo}; classes {list(meta.classes.values())}")
        elif args.comando == "classificar":
            cfg = carregar_config(args.config)
            res = classificar(args.ortomosaico, args.talhoes, args.modelo, args.saida, cfg)
            print(f"Máscara gravada em {res.caminho_mascara}; pixels por classe: {res.pixels_por_classe}")
            if res.caminho_probabilidade:
                print(f"Probabilidade da classe cana em {res.caminho_probabilidade}")
        elif args.comando == "objetos-treinar":
            cfg = carregar_config(args.config)
            areas = [AreaObjetos(Path(o), Path(t), None if d == "-" else Path(d), Path(a), nome=Path(o).stem)
                     for o, t, d, a in args.area]
            meta = treinar_objetos(areas, args.modelo, cfg)
            print(f"Modelo gravado em {args.modelo}; amostras {meta.amostras_por_classe}; "
                  f"descartadas {meta.descartes}")
            _imprimir_validacao(meta.validacao)
        elif args.comando == "objetos-classificar":
            cfg = carregar_config(args.config)
            cont = classificar_objetos(AreaObjetos(args.ortomosaico, args.talhoes, args.deteccao), args.modelo,
                                       args.saida, cfg)
            print(f"Máscara gravada em {args.saida}; pixels por classe: {cont}")
        else:
            rel = avaliar(args.mascara, args.teste)
            print(rel.aviso)
            print(f"pixels avaliados={rel.n_pixels}  acurácia global="
                  f"{'-' if rel.acuracia_global is None else f'{rel.acuracia_global:.3f}'}")
            for nome, v in rel.iou_por_classe.items():
                print(f"  IoU {nome}: {'-' if v is None else f'{v:.3f}'}")
            if args.relatorio:
                args.relatorio.write_text(json.dumps(asdict(rel), ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except ErroMascaras as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Erro inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
