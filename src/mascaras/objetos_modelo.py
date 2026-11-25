"""Treino, validação e classificação da etapa 2 (objetos) com amostras pontuais.

Amostras: GeoPackage ou shapefile de pontos com o campo `classe` (`cana` ou `daninha`, ou os códigos
1 e 2). Cada ponto rotula o superpixel onde cai. Ponto fora do verde ou fora da área útil é descartado
e contado. Dois pontos de classes diferentes no mesmo superpixel: os dois são descartados (conflito).

Validação: deixando um talhão de fora por vez (o modelo nunca vê o talhão em que é testado), com e sem
os atributos de posição. Nenhum limite de aceitação é fixado (escopo, seção 8, item 4).
O modelo é gravado com joblib (pickle): só carregar modelos gerados pelo próprio projeto.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from shapely.geometry import Point
from sklearn.ensemble import RandomForestClassifier

from . import __version__
from .config import ConfigMascaras
from .objetos import (ATRIBUTOS_BASE, abrir_contexto, janela_do_pixel, janelas_fixas, nomes_atributos,
                      processar_janela)
from .raster import criar_geotiff, ler_vetor, verificar_crs
from .tipos import CANA, DANINHA, FUNDO, IGNORADO, NOMES_CLASSES, ErroContrato, ErroLeitura

CLASSES_OBJETOS = (CANA, DANINHA)
CAMPO_CLASSE = "classe"


@dataclass(frozen=True)
class AreaObjetos:
    ortomosaico: Path
    talhoes: Path
    deteccao: Path | None  # GeoPackage da detecção (fileiras); obrigatório com usar_posicao
    amostras: Path | None = None  # só no treino
    nome: str = ""


@dataclass
class MetadadosObjetos:
    tipo: str
    classes: dict[str, str]
    atributos: list[str]
    usar_posicao: bool
    tamanho_segmento_m: float
    compacidade_slic: float
    halo_objetos_m: float
    resolucao_trabalho_m: float
    bandas_rgb: list[int]
    largura_faixa_m: float
    lado_janela_px: int
    amostras_por_classe: dict[str, int]
    descartes: dict[str, int]
    validacao: dict
    areas_treino: list[str]
    versao_pacote: str
    versao_sklearn: str
    criado_em: str
    parametros_modelo: dict = field(default_factory=dict)

    def gravar(self, caminho: Path) -> None:
        Path(caminho).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def ler(cls, caminho: Path) -> "MetadadosObjetos":
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ErroLeitura(f"metadados do modelo não encontrados: {caminho}")
        try:
            meta = cls(**json.loads(caminho.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ErroContrato(f"{caminho} não é um modelo de objetos (etapa 2): {exc}") from exc
        if meta.tipo != "objetos":
            raise ErroContrato(f"{caminho} não é um modelo de objetos (etapa 2)")
        return meta


# ---------------------------------------------------------------- amostras

def ler_amostras(caminho: Path, crs_ref) -> list[tuple[Point, int]]:
    gdf = ler_vetor(caminho, "amostras pontuais")
    if CAMPO_CLASSE not in gdf.columns:
        raise ErroLeitura(f"amostras sem o campo '{CAMPO_CLASSE}' em {caminho}")
    verificar_crs({"ortomosaico": crs_ref, "amostras": gdf.crs})
    por_nome = {"cana": CANA, "daninha": DANINHA}
    saida = []
    for i, linha in gdf.iterrows():
        geom, bruto = linha.geometry, linha[CAMPO_CLASSE]
        if geom is None or geom.is_empty or geom.geom_type != "Point":
            raise ErroContrato(f"amostra {i}: geometria vazia ou não é ponto")
        if isinstance(bruto, str) and bruto.strip().lower() in por_nome:
            codigo = por_nome[bruto.strip().lower()]
        else:
            try:
                codigo = int(bruto)
            except (TypeError, ValueError):
                codigo = -1
        if codigo not in CLASSES_OBJETOS:
            raise ErroContrato(f"amostra {i}: classe {bruto!r} inválida; use 'cana' ou 'daninha'")
        saida.append((geom, codigo))
    return saida


@dataclass
class Amostragem:
    X: np.ndarray
    y: np.ndarray
    grupos: np.ndarray  # "área:talhão" de cada amostra
    descartes: dict[str, int]


def amostrar_area(area: AreaObjetos, cfg: ConfigMascaras) -> Amostragem:
    """Atributos do superpixel de cada ponto de amostra da área."""
    ctx = abrir_contexto(area.ortomosaico, area.talhoes, area.deteccao, cfg)
    try:
        pontos = ler_amostras(area.amostras, ctx.orto.crs)
        g = ctx.orto.grade
        descartes = {"fora_da_area_util": 0, "fora_do_verde": 0, "conflito": 0}
        por_janela: dict[tuple, list] = {}
        for p, c in pontos:
            talhao = next((i for i, poli in zip(ctx.talhoes.ids, ctx.talhoes.poligonos_util) if poli.contains(p)),
                          None)
            if talhao is None:
                descartes["fora_da_area_util"] += 1
                continue
            col, lin = ~g.transform * (p.x, p.y)
            lin, col = int(lin), int(col)
            por_janela.setdefault(janela_do_pixel(lin, col, g, cfg.lado_janela_px), []).append(
                (lin, col, c, talhao))
        xs, ys, gs = [], [], []
        for (l0, c0, h, w), lista in por_janela.items():
            jan = processar_janela(ctx, l0, c0, h, w, cfg, cfg.usar_posicao)
            por_segmento: dict[int, list[tuple[int, str]]] = {}
            for lin, col, c, talhao in lista:
                s = int(jan.segmentos[lin - l0, col - c0])
                if s == 0:
                    descartes["fora_do_verde"] += 1
                    continue
                por_segmento.setdefault(s, []).append((c, talhao))
            for s, rotulos in por_segmento.items():
                if len({c for c, _ in rotulos}) > 1:  # classes diferentes no mesmo superpixel
                    descartes["conflito"] += len(rotulos)
                    continue
                k = int(np.searchsorted(jan.ids, s))  # vários pontos iguais no superpixel contam uma vez
                xs.append(jan.X[k])
                ys.append(rotulos[0][0])
                gs.append(f"{area.nome}:{rotulos[0][1]}")
        n = len(xs)
        k = len(nomes_atributos(cfg.usar_posicao))
        return Amostragem(np.asarray(xs, np.float32).reshape(n, k), np.asarray(ys, np.uint8), np.asarray(gs),
                          descartes)
    finally:
        ctx.fechar()


# ---------------------------------------------------------------- validação

def _modelo(cfg: ConfigMascaras) -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=cfg.n_arvores, max_depth=cfg.profundidade_max or None,
                                  random_state=cfg.semente, n_jobs=cfg.n_jobs, class_weight="balanced")


def validar_por_talhao(X: np.ndarray, y: np.ndarray, grupos: np.ndarray, cfg: ConfigMascaras) -> dict:
    """Deixa um talhão de fora por vez. Só testa o talhão se o treino restante tiver as duas classes."""
    resultado = {"por_talhao": {}, "pulados": {}}
    total = np.zeros((2, 2), dtype=np.int64)  # linha = amostra, coluna = previsto; ordem cana, daninha
    for gr in sorted(set(grupos)):
        teste = grupos == gr
        treino = ~teste
        if set(np.unique(y[treino])) != set(CLASSES_OBJETOS):
            resultado["pulados"][gr] = "o treino sem este talhão não tem as duas classes"
            continue
        prev = _modelo(cfg).fit(X[treino], y[treino]).predict(X[teste])
        m = np.zeros((2, 2), dtype=np.int64)
        for a, b in zip(y[teste], prev):
            m[CLASSES_OBJETOS.index(a), CLASSES_OBJETOS.index(b)] += 1
        total += m
        resultado["por_talhao"][gr] = _resumo(m)
    resultado["global"] = _resumo(total) if total.sum() else None
    return resultado


def _resumo(m: np.ndarray) -> dict:
    def taxa(a, b):
        return None if b == 0 else round(float(a / b), 3)
    return {"n": int(m.sum()), "matriz_amostra_x_previsto": m.tolist(),
            "acerto_cana": taxa(m[0, 0], m[0].sum()), "acerto_daninha": taxa(m[1, 1], m[1].sum()),
            "acuracia": taxa(np.trace(m), m.sum())}


# ---------------------------------------------------------------- treino

def treinar_objetos(areas: list[AreaObjetos], caminho_modelo: Path, cfg: ConfigMascaras) -> MetadadosObjetos:
    if not areas:
        raise ErroContrato("informe ao menos uma área com amostras")
    partes = []
    descartes: dict[str, int] = {}
    for a in areas:
        print(f"[{a.nome}] superpixels e atributos das amostras...", flush=True)
        am = amostrar_area(a, cfg)
        partes.append(am)
        for k, v in am.descartes.items():
            descartes[k] = descartes.get(k, 0) + v
    X = np.concatenate([p.X for p in partes])
    y = np.concatenate([p.y for p in partes])
    grupos = np.concatenate([p.grupos for p in partes])
    presentes = set(np.unique(y).tolist())
    if presentes != set(CLASSES_OBJETOS):
        raise ErroContrato(f"amostras válidas só de {[NOMES_CLASSES[c] for c in presentes]}: "
                           "é preciso cana e daninha. Descartes: " + str(descartes))
    n_por = {NOMES_CLASSES[c]: int((y == c).sum()) for c in CLASSES_OBJETOS}
    print(f"Amostras válidas: {n_por}; descartadas: {descartes}", flush=True)

    validacao = {"com_posicao" if cfg.usar_posicao else "sem_posicao": validar_por_talhao(X, y, grupos, cfg)}
    if cfg.usar_posicao:  # mesma validação só com cor, textura e forma, para medir o peso da posição
        validacao["sem_posicao"] = validar_por_talhao(X[:, :len(ATRIBUTOS_BASE)], y, grupos, cfg)

    modelo = _modelo(cfg).fit(X, y)
    caminho_modelo = Path(caminho_modelo)
    try:
        caminho_modelo.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(modelo, caminho_modelo)
    except OSError as exc:
        raise ErroLeitura(f"não foi possível gravar {caminho_modelo}: {exc}") from exc
    nomes = nomes_atributos(cfg.usar_posicao)
    meta = MetadadosObjetos(
        tipo="objetos", classes={str(c): NOMES_CLASSES[c] for c in CLASSES_OBJETOS}, atributos=nomes,
        usar_posicao=cfg.usar_posicao, tamanho_segmento_m=cfg.tamanho_segmento_m,
        compacidade_slic=cfg.compacidade_slic, halo_objetos_m=cfg.halo_objetos_m,
        resolucao_trabalho_m=cfg.resolucao_trabalho_m, bandas_rgb=list(cfg.bandas_rgb),
        largura_faixa_m=cfg.largura_faixa_m, lado_janela_px=cfg.lado_janela_px, amostras_por_classe=n_por,
        descartes=descartes, validacao=validacao, areas_treino=[str(a.amostras) for a in areas],
        versao_pacote=__version__, versao_sklearn=sklearn.__version__,
        criado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        parametros_modelo={"tipo": "RandomForestClassifier", "n_estimators": cfg.n_arvores,
                           "max_depth": cfg.profundidade_max or None, "class_weight": "balanced",
                           "importancia_atributos": dict(zip(nomes, np.round(modelo.feature_importances_, 4)
                                                             .tolist()))})
    meta.gravar(caminho_modelo.with_suffix(".json"))
    return meta


# ---------------------------------------------------------------- classificação

def classificar_objetos(area: AreaObjetos, caminho_modelo: Path, caminho_saida: Path,
                        cfg: ConfigMascaras) -> dict[str, int]:
    """Grava o GeoTIFF de classes (códigos da seção 3): cana e daninha nos superpixels do verde, fundo no
    resto da área útil, 0 fora dela. Os parâmetros de segmentação vêm dos metadados do modelo."""
    caminho_modelo = Path(caminho_modelo)
    if not caminho_modelo.is_file():
        raise ErroLeitura(f"modelo não encontrado: {caminho_modelo}")
    meta = MetadadosObjetos.ler(caminho_modelo.with_suffix(".json"))
    try:
        modelo = joblib.load(caminho_modelo)
    except Exception as exc:
        raise ErroLeitura(f"não foi possível carregar o modelo {caminho_modelo}: {exc}") from exc
    cfg = replace(cfg, usar_posicao=meta.usar_posicao, tamanho_segmento_m=meta.tamanho_segmento_m,
                  compacidade_slic=meta.compacidade_slic, halo_objetos_m=meta.halo_objetos_m,
                  resolucao_trabalho_m=meta.resolucao_trabalho_m, bandas_rgb=tuple(meta.bandas_rgb),
                  largura_faixa_m=meta.largura_faixa_m, lado_janela_px=meta.lado_janela_px)
    ctx = abrir_contexto(area.ortomosaico, area.talhoes, area.deteccao if meta.usar_posicao else None, cfg)
    cont = np.zeros(len(NOMES_CLASSES), dtype=np.int64)
    try:
        g = ctx.orto.grade
        janelas = list(janelas_fixas(g, ctx.talhoes.uniao_util.bounds, cfg.lado_janela_px))
        with criar_geotiff(caminho_saida, g, ctx.orto.crs, "uint8", nodata=IGNORADO) as dst:
            for k, (lin, col, h, w) in enumerate(janelas, start=1):
                jan = processar_janela(ctx, lin, col, h, w, cfg, meta.usar_posicao)
                saida = np.full((h, w), IGNORADO, dtype=np.uint8)
                saida[jan.valido & ~jan.verde] = FUNDO
                if jan.ids.size:
                    prev = modelo.predict(jan.X).astype(np.uint8)
                    tabela = np.zeros(int(jan.ids.max()) + 1, dtype=np.uint8)
                    tabela[jan.ids] = prev
                    m = jan.segmentos > 0
                    saida[m] = tabela[jan.segmentos[m]]
                cont += np.bincount(saida.ravel(), minlength=256)[:len(NOMES_CLASSES)]
                dst.write(saida, 1, window=((lin, lin + h), (col, col + w)))
                if k % 20 == 0:
                    print(f"janelas {k}/{len(janelas)}", flush=True)
    finally:
        ctx.fechar()
    return {NOMES_CLASSES[c]: int(cont[c]) for c in NOMES_CLASSES}
