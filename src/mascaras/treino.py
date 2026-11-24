"""Treino do nível 1: classificador por pixel (docs/escopo-mascaras.md, seções 2 e 7.1).

Treino feito uma vez com vários talhões (pares ortomosaico + rótulos) e reaproveitado. A amostragem é
estratificada por classe, em duas passagens por janelas: a 1ª conta os rótulos, a 2ª sorteia os pixels.
O modelo é gravado com joblib (pickle): só carregar modelos gerados pelo próprio projeto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import json

import joblib
import numpy as np
import rasterio
import sklearn
from sklearn.ensemble import RandomForestClassifier

from . import __version__
from .atributos import calcular_atributos, nomes_atributos
from .config import ConfigMascaras
from .raster import Grade, Ortomosaico, verificar_crs
from .tipos import CLASSES_TREINO, NOMES_CLASSES, CANA, ErroContrato, ErroLeitura, MetadadosModelo, caminho_metadados


@dataclass(frozen=True)
class ParTreino:
    ortomosaico: Path
    rotulos: Path


def _abrir_rotulos(caminho: Path, orto: Ortomosaico) -> rasterio.io.DatasetReader:
    """Abre o GeoTIFF de rótulos e confere que está na grade de trabalho do ortomosaico."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroLeitura(f"rótulos não encontrados: {caminho}")
    ds = rasterio.open(caminho)
    verificar_crs({"ortomosaico": orto.crs, "rotulos": ds.crs})
    g: Grade = orto.grade
    if ds.width != g.largura or ds.height != g.altura or not ds.transform.almost_equals(g.transform):
        ds.close()
        raise ErroContrato(
            f"{caminho.name} não está na grade de trabalho do ortomosaico (resolução {g.res} m, origem no "
            "canto noroeste). Gere os rótulos com `python -m mascaras pseudo-rotulos` e a mesma resolucao_trabalho_m.")
    return ds


def _janelas_rotulo(ds, lado: int):
    for lin in range(0, ds.height, lado):
        for col in range(0, ds.width, lado):
            yield lin, col, min(lado, ds.height - lin), min(lado, ds.width - col)


def contar_rotulos(pares: list[ParTreino], cfg: ConfigMascaras) -> np.ndarray:
    """Pixels por código de classe (0 a 4), somados em todos os pares."""
    cont = np.zeros(len(NOMES_CLASSES), dtype=np.int64)
    for par in pares:
        orto = Ortomosaico(par.ortomosaico, cfg.bandas_rgb, cfg.resolucao_trabalho_m)
        try:
            with _abrir_rotulos(par.rotulos, orto) as ds:
                for lin, col, h, w in _janelas_rotulo(ds, cfg.lado_janela_px):
                    r = ds.read(1, window=((lin, lin + h), (col, col + w)))
                    cont += np.bincount(r.ravel(), minlength=256)[:len(NOMES_CLASSES)]
        finally:
            orto.fechar()
    return cont


def amostrar(pares: list[ParTreino], cfg: ConfigMascaras) -> tuple[np.ndarray, np.ndarray]:
    """Matriz de atributos X (n, k) e rótulos y (n,), no máximo `max_amostras_por_classe` por classe."""
    cont = contar_rotulos(pares, cfg)
    prob = {c: min(1.0, cfg.max_amostras_por_classe / cont[c]) if cont[c] else 0.0 for c in CLASSES_TREINO}
    rng = np.random.default_rng(cfg.semente)
    xs, ys = [], []
    borda = cfg.raio_vizinhanca_px
    for par in pares:
        orto = Ortomosaico(par.ortomosaico, cfg.bandas_rgb, cfg.resolucao_trabalho_m)
        try:
            with _abrir_rotulos(par.rotulos, orto) as ds:
                for lin, col, h, w in _janelas_rotulo(ds, cfg.lado_janela_px):
                    r = ds.read(1, window=((lin, lin + h), (col, col + w)))
                    sorteio = np.zeros(r.shape, dtype=bool)
                    for c in CLASSES_TREINO:
                        m = r == c
                        if prob[c] > 0 and m.any():
                            sorteio |= m & (rng.random(r.shape) < prob[c])
                    if not sorteio.any():
                        continue
                    dados, valido = orto.ler(lin, col, h, w, borda=borda)
                    atr = calcular_atributos(dados, cfg.atributos, borda)
                    if borda:
                        atr, valido = atr[:, borda:-borda, borda:-borda], valido[borda:-borda, borda:-borda]
                    sel = sorteio & valido & np.isfinite(atr).all(axis=0)
                    if sel.any():
                        xs.append(atr[:, sel].T)
                        ys.append(r[sel])
        finally:
            orto.fechar()
    if not xs:
        raise ErroContrato("nenhum pixel rotulado e válido nos pares de treino")
    return np.concatenate(xs).astype(np.float32), np.concatenate(ys).astype(np.uint8)


def _talhoes_do_resumo(rotulos: Path) -> list[str]:
    resumo = Path(rotulos).with_suffix(".json")
    if resumo.is_file():
        try:
            return [str(t) for t in json.loads(resumo.read_text(encoding="utf-8")).get("talhoes", [])]
        except (json.JSONDecodeError, AttributeError):
            return []
    return []


def treinar(pares: list[ParTreino], caminho_modelo: Path, cfg: ConfigMascaras) -> MetadadosModelo:
    """Treina o Random Forest e grava `modelo.joblib` e `modelo.json` (metadados).

    Raises: ErroContrato se faltar a classe cana ou se houver menos de duas classes.
    """
    if not pares:
        raise ErroContrato("informe ao menos um par ortomosaico + rótulos")
    print(f"Amostrando pixels de {len(pares)} par(es)...", flush=True)
    X, y = amostrar(pares, cfg)
    presentes = sorted(int(c) for c in np.unique(y))
    if CANA not in presentes or len(presentes) < 2:
        raise ErroContrato(f"amostras só das classes {[NOMES_CLASSES[c] for c in presentes]}: "
                           "é preciso cana e ao menos outra classe")
    n_por = {NOMES_CLASSES[c]: int((y == c).sum()) for c in presentes}
    print(f"Amostras por classe: {n_por}. Treinando...", flush=True)
    params = dict(n_estimators=cfg.n_arvores, max_depth=cfg.profundidade_max or None,
                  random_state=cfg.semente, n_jobs=cfg.n_jobs)
    modelo = RandomForestClassifier(**params).fit(X, y)
    caminho_modelo = Path(caminho_modelo)
    try:
        caminho_modelo.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(modelo, caminho_modelo)
    except OSError as exc:
        raise ErroLeitura(f"não foi possível gravar {caminho_modelo}: {exc}") from exc
    talhoes = sorted({t for p in pares for t in _talhoes_do_resumo(p.rotulos)})
    meta = MetadadosModelo(
        nivel=1, classes={str(c): NOMES_CLASSES[c] for c in presentes}, bandas_rgb=list(cfg.bandas_rgb),
        resolucao_trabalho_m=cfg.resolucao_trabalho_m, atributos=list(cfg.atributos),
        raio_vizinhanca_px=cfg.raio_vizinhanca_px, versao_pacote=__version__, versao_sklearn=sklearn.__version__,
        areas_treino=[str(p.rotulos) for p in pares], talhoes_treino=talhoes, amostras_por_classe=n_por,
        criado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        parametros_modelo={"tipo": "RandomForestClassifier", **params,
                           "nomes_atributos": nomes_atributos(cfg.atributos, cfg.raio_vizinhanca_px)})
    meta.gravar(caminho_metadados(caminho_modelo))
    return meta
