"""Atributos por pixel do nível 1 (docs/escopo-mascaras.md, seção 7.1). Funções puras."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter


def exg_normalizado(bandas: np.ndarray) -> np.ndarray:
    """(2g - r - b) com r, g, b cromáticos (cada banda dividida pela soma). Soma zero vira NaN."""
    b = bandas.astype(np.float32)
    soma = b[0] + b[1] + b[2]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (2.0 * b[1] - b[0] - b[2]) / soma
    out[~np.isfinite(out)] = np.nan
    return out.astype(np.float32)


def gli(bandas: np.ndarray) -> np.ndarray:
    """Green Leaf Index: (2g - r - b) / (2g + r + b). Denominador zero vira NaN."""
    b = bandas.astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (2.0 * b[1] - b[0] - b[2]) / (2.0 * b[1] + b[0] + b[2])
    out[~np.isfinite(out)] = np.nan
    return out.astype(np.float32)


def nomes_atributos(atributos: tuple[str, ...] | list[str], raio_vizinhanca_px: int) -> list[str]:
    nomes = list(atributos)
    if raio_vizinhanca_px > 0:
        nomes += ["exg_media_viz", "exg_desvio_viz"]
    return nomes


def calcular_atributos(bandas: np.ndarray, atributos: tuple[str, ...] | list[str],
                       raio_vizinhanca_px: int) -> np.ndarray:
    """bandas (3, h, w) em 0-255 -> (n_atributos, h, w) float32, na ordem de `nomes_atributos`.

    R, G e B entram divididos por 255. Os atributos de vizinhança usam o ExG; quem chama deve ler a
    janela com uma borda de `raio_vizinhanca_px` pixels para que a borda não seja afetada.
    NaN (pixel preto, divisão por zero) fica NaN: quem chama trata como inválido.
    """
    b = bandas.astype(np.float32)
    exg = None
    camadas = []
    for nome in atributos:
        if nome in ("r", "g", "b"):
            camadas.append(b["rgb".index(nome)] / 255.0)
        elif nome == "exg":
            exg = exg_normalizado(b) if exg is None else exg
            camadas.append(exg)
        elif nome == "gli":
            camadas.append(gli(b))
        else:  # validado na configuração
            raise ValueError(nome)
    if raio_vizinhanca_px > 0:
        exg = exg_normalizado(b) if exg is None else exg
        tam = 2 * raio_vizinhanca_px + 1
        base = np.nan_to_num(exg, nan=0.0)
        media = uniform_filter(base, size=tam, mode="nearest")
        quad = uniform_filter(base * base, size=tam, mode="nearest")
        desvio = np.sqrt(np.maximum(quad - media * media, 0.0))
        camadas += [media.astype(np.float32), desvio.astype(np.float32)]
    return np.stack(camadas).astype(np.float32)
