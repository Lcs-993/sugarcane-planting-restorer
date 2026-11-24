"""Avaliação por classe contra um conjunto de teste manual (docs/escopo-mascaras.md, seção 8, item 2).

A referência são polígonos desenhados e revisados à mão, com o campo `classe`. Pseudo-rótulo nunca é
referência: herda os erros do método atual. Nenhum limite de aceitação é fixado (seção 8, item 4).
Esta avaliação mede a máscara, não a tarefa: a avaliação final é a da detecção contra RTK (item 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import box
from shapely.ops import unary_union

from .pseudo_rotulos import ler_correcoes
from .raster import Grade
from .tipos import CLASSES_TREINO, NOMES_CLASSES, ErroContrato, ErroLeitura

LADO = 1024
AVISO = ("Métrica sobre o conjunto de teste manual: mede a máscara, não a posição das fileiras. "
         "A avaliação que decide é a da detecção contra RTK (docs/escopo-mascaras.md, seção 8, item 3).")


@dataclass
class RelatorioAvaliacao:
    classes: list[str]  # ordem das linhas e colunas da matriz
    matriz_confusao: list[list[int]]  # linha = referência, coluna = máscara
    iou_por_classe: dict[str, float | None]
    acuracia_global: float | None
    n_pixels: int
    aviso: str = AVISO


def matriz_confusao(ref: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Matriz (4, 5) sobre as classes de treino (1 a 4): linha = referência, coluna = máscara, com uma
    coluna extra para previsão 0 (sem dado), que conta como erro. Pixel de referência 0 é ignorado."""
    n = len(CLASSES_TREINO)
    idx = np.full(256, -1, dtype=np.int64)
    idx[list(CLASSES_TREINO)] = np.arange(n)
    m = np.zeros((n, n + 1), dtype=np.int64)
    r, p = idx[ref], idx[pred]
    ok = r >= 0
    np.add.at(m, (r[ok], np.where(p >= 0, p, n)[ok]), 1)
    return m


def iou_por_classe(m: np.ndarray) -> dict[str, float | None]:
    """IoU = VP / (VP + FP + FN); None se a classe não aparece nem na referência nem na máscara."""
    iou = {}
    for i, c in enumerate(CLASSES_TREINO):
        vp = m[i, i]
        den = m[i, :].sum() + m[:, i].sum() - vp
        iou[NOMES_CLASSES[c]] = float(vp / den) if den else None
    return iou


def avaliar(caminho_mascara: Path, caminho_teste: Path) -> RelatorioAvaliacao:
    """Compara a máscara de classes com os polígonos de teste manual, por janelas."""
    caminho_mascara = Path(caminho_mascara)
    if not caminho_mascara.is_file():
        raise ErroLeitura(f"máscara não encontrada: {caminho_mascara}")
    with rasterio.open(caminho_mascara) as ds:
        poligonos = ler_correcoes(caminho_teste, ds.crs)
        if not poligonos:
            raise ErroContrato(f"nenhum polígono de teste em {caminho_teste}")
        res = abs(ds.transform.a)
        grade = Grade(transform=ds.transform, largura=ds.width, altura=ds.height, res=res)
        alvo = unary_union([g for g, _ in poligonos]).bounds
        n = len(CLASSES_TREINO)
        total = np.zeros((n, n + 1), dtype=np.int64)
        for lin, col, h, w in grade.janelas(alvo, LADO):
            bx = box(*grade.bounds_janela(lin, col, h, w))
            formas = [(g.intersection(bx), v) for g, v in poligonos if g.intersects(bx)]
            formas = [(f, v) for f, v in formas if not f.is_empty]
            if not formas:
                continue
            ref = rasterize(formas, out_shape=(h, w), transform=grade.transform_janela(lin, col), fill=0,
                            dtype="uint8")
            pred = ds.read(1, window=((lin, lin + h), (col, col + w)))
            total += matriz_confusao(ref, pred)
    iou = iou_por_classe(total)
    n_pix = int(total.sum())
    acc = float(np.trace(total[:, :n]) / n_pix) if n_pix else None
    return RelatorioAvaliacao(
        classes=[NOMES_CLASSES[c] for c in CLASSES_TREINO] + ["(sem previsão)"],
        matriz_confusao=total.tolist(), iou_por_classe=iou, acuracia_global=acc, n_pixels=n_pix)

