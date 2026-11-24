"""Classificação do ortomosaico por janelas com o modelo do nível 1 (docs/escopo-mascaras.md, seção 4).

A saída é o GeoTIFF de classes que a detecção lê com `perfil_sobre: mascara`. Fora dos talhões (com
buffer interno) e em pixel sem dado: 0 (ignorado). Bandas, resolução e atributos vêm dos metadados do
modelo, não da configuração: um modelo só é usado do jeito que foi treinado.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import sklearn

from .atributos import calcular_atributos
from .config import ConfigMascaras
from .raster import Ortomosaico, criar_geotiff, ler_talhoes, mascara_poligono
from .tipos import CANA, IGNORADO, NOMES_CLASSES, ErroContrato, ErroLeitura, MetadadosModelo, caminho_metadados


@dataclass(frozen=True)
class ResumoClassificacao:
    pixels_por_classe: dict[str, int]
    caminho_mascara: str
    caminho_probabilidade: str | None


def carregar_modelo(caminho_modelo: Path):
    """Modelo e metadados. Só carregar modelos gerados pelo próprio projeto (joblib = pickle)."""
    caminho_modelo = Path(caminho_modelo)
    if not caminho_modelo.is_file():
        raise ErroLeitura(f"modelo não encontrado: {caminho_modelo}")
    meta = MetadadosModelo.ler(caminho_metadados(caminho_modelo))
    if meta.nivel != 1:
        raise ErroContrato(f"modelo de nível {meta.nivel}: esta versão só classifica com o nível 1")
    if meta.versao_sklearn != sklearn.__version__:
        warnings.warn(f"modelo treinado com scikit-learn {meta.versao_sklearn}; instalado {sklearn.__version__}",
                      stacklevel=2)
    try:
        modelo = joblib.load(caminho_modelo)
    except Exception as exc:
        raise ErroLeitura(f"não foi possível carregar o modelo {caminho_modelo}: {exc}") from exc
    return modelo, meta


def classificar(caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_modelo: Path, caminho_saida: Path,
                cfg: ConfigMascaras) -> ResumoClassificacao:
    """Grava a máscara de classes (uint8) e, se `cfg.gravar_probabilidade_cana`, a probabilidade da
    classe cana (float32, ao lado, com sufixo `_prob_cana`)."""
    modelo, meta = carregar_modelo(caminho_modelo)
    classes = np.asarray(modelo.classes_, dtype=np.uint8)
    i_cana = int(np.flatnonzero(classes == CANA)[0]) if CANA in classes else None
    bandas = tuple(meta.bandas_rgb)
    borda = meta.raio_vizinhanca_px
    orto = Ortomosaico(caminho_ortomosaico, bandas, meta.resolucao_trabalho_m)
    caminho_saida = Path(caminho_saida)
    caminho_prob = (caminho_saida.with_name(caminho_saida.stem + "_prob_cana.tif")
                    if cfg.gravar_probabilidade_cana else None)
    cont = np.zeros(len(NOMES_CLASSES), dtype=np.int64)
    try:
        talhoes = ler_talhoes(caminho_talhoes, cfg.campo_id_talhao, cfg.buffer_interno_m, orto.crs)
        g = orto.grade
        dst = criar_geotiff(caminho_saida, g, orto.crs, "uint8", nodata=IGNORADO)
        dst_p = criar_geotiff(caminho_prob, g, orto.crs, "float32", nodata=np.nan) if caminho_prob else None
        try:
            janelas = list(g.janelas(talhoes.uniao_util.bounds, cfg.lado_janela_px))
            for k, (lin, col, h, w) in enumerate(janelas, start=1):
                dentro = mascara_poligono(talhoes.uniao_util, g, lin, col, h, w)
                saida = np.full((h, w), IGNORADO, dtype=np.uint8)
                prob = np.full((h, w), np.nan, dtype=np.float32)
                if dentro.any():
                    dados, valido = orto.ler(lin, col, h, w, borda=borda)
                    atr = calcular_atributos(dados, meta.atributos, borda)
                    if borda:
                        atr, valido = atr[:, borda:-borda, borda:-borda], valido[borda:-borda, borda:-borda]
                    sel = dentro & valido & np.isfinite(atr).all(axis=0)
                    if sel.any():
                        X = atr[:, sel].T
                        if dst_p is not None and i_cana is not None:
                            p = modelo.predict_proba(X)
                            saida[sel] = classes[np.argmax(p, axis=1)]
                            prob[sel] = p[:, i_cana]
                        else:
                            saida[sel] = modelo.predict(X).astype(np.uint8)
                cont += np.bincount(saida.ravel(), minlength=256)[:len(NOMES_CLASSES)]
                dst.write(saida, 1, window=((lin, lin + h), (col, col + w)))
                if dst_p is not None:
                    dst_p.write(prob, 1, window=((lin, lin + h), (col, col + w)))
                if k % 20 == 0:
                    print(f"janelas {k}/{len(janelas)}", flush=True)
        finally:
            dst.close()
            if dst_p is not None:
                dst_p.close()
    finally:
        orto.fechar()
    return ResumoClassificacao(pixels_por_classe={NOMES_CLASSES[c]: int(cont[c]) for c in NOMES_CLASSES},
                               caminho_mascara=str(caminho_saida),
                               caminho_probabilidade=str(caminho_prob) if caminho_prob else None)
