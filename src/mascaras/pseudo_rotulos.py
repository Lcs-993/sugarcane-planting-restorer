"""Pseudo-rótulos a partir de uma execução da detecção de linhas (docs/escopo-mascaras.md, seção 6).

Lê o GeoPackage da detecção (camadas `fileiras` e `trechos`) como arquivo: não importa `deteccao_linhas`.

Regras (todas HIPÓTESE, menos a largura da faixa, que é premissa):
1. Trecho confiável: ponto `detectado` com confiança >= `limiar_confianca_pseudo`, sem nenhum ponto
   `interpolado` ou `duvidoso` (ou de confiança baixa) a menos de `vizinhos_excluidos` pontos dele.
   Cada ponto responde pelo pedaço da fileira entre os pontos médios com seus vizinhos.
2. Só se rotula a zona até `meia_largura_zona_m` do eixo de um trecho confiável. Fora dela: ignorado.
3. Na zona, verde (ExG normalizado >= Otsu do talhão):
   - dentro da faixa do trecho confiável (largura_faixa_m) -> cana;
   - dentro da faixa mais a margem de qualquer fileira detectada -> ignorado (perfilhamento);
   - fora disso -> ignorado (padrão; o foco é a cana e a folha passa da faixa) ou, com
     `daninha_por_posicao`, daninha. Sem essa opção, daninha só vem dos polígonos manuais (regra 5).
4. Na zona, não verde -> fundo; com `sombra_brilho_max` > 0, não verde e mais escuro que isso -> sombra.
5. Polígonos de correção manual (campo `classe`) sobrescrevem tudo, na ordem do arquivo.
O pseudo-rótulo herda os erros do método atual: não serve para avaliar (seção 8).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.ops import substring, unary_union

from . import __version__
from .atributos import exg_normalizado
from .config import ConfigMascaras
from .raster import Ortomosaico, criar_geotiff, ler_talhoes, ler_vetor, mascara_poligono, verificar_crs
from .tipos import (CANA, DANINHA, FUNDO, IGNORADO, NOMES_CLASSES, SOMBRA, ErroContrato, ErroLeitura)

BINS_OTSU = 3000  # histograma fixo do ExG normalizado em [-1, 2]: só resolução numérica, não hipótese
FAIXA_EXG = (-1.0, 2.0)
CAMPO_CLASSE = "classe"


@dataclass
class ResumoPseudoRotulos:
    talhoes: list[str]
    limiar_exg_por_talhao: dict[str, float]
    n_fileiras: int
    comprimento_confiavel_m: float
    comprimento_total_m: float
    n_poligonos_correcao: int
    pixels_por_classe: dict[str, int] = field(default_factory=dict)
    versao_pacote: str = __version__
    aviso: str = ("Pseudo-rótulo gerado pela detecção ExG + Otsu: herda os erros dela. "
                  "Não usar como referência de avaliação.")


# ---------------------------------------------------------------- Otsu

def otsu_histograma(contagens: np.ndarray, bordas: np.ndarray) -> float:
    """Limiar de Otsu num histograma; devolve a borda superior do bin ótimo (verde = valor >= limiar)."""
    total = contagens.sum()
    if total == 0:
        raise ErroContrato("histograma vazio")
    centros = (bordas[:-1] + bordas[1:]) / 2.0
    p = contagens / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * centros)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = (mu[-1] * omega - mu) ** 2 / (omega * (1.0 - omega))
    sigma_b[~np.isfinite(sigma_b)] = -1.0
    return float(bordas[int(np.argmax(sigma_b)) + 1])


def limiares_otsu(orto: Ortomosaico, ids: tuple[str, ...], poligonos, cfg: ConfigMascaras) -> dict[str, float]:
    """Otsu do ExG normalizado por talhão, com o histograma acumulado por janelas."""
    bordas = np.linspace(FAIXA_EXG[0], FAIXA_EXG[1], BINS_OTSU + 1)
    saida = {}
    for ident, poli in zip(ids, poligonos):
        cont = np.zeros(BINS_OTSU, dtype=np.int64)
        for lin, col, h, w in orto.grade.janelas(poli.bounds, cfg.lado_janela_px):
            dados, valido = orto.ler(lin, col, h, w)
            ok = valido & mascara_poligono(poli, orto.grade, lin, col, h, w)
            if ok.any():
                v = exg_normalizado(dados)[ok]
                v = v[np.isfinite(v)]
                cont += np.histogram(np.clip(v, *FAIXA_EXG), bins=bordas)[0]
        if cont.sum() == 0:
            raise ErroContrato(f"talhão {ident!r}: área útil sem pixels válidos no ortomosaico")
        saida[ident] = otsu_histograma(cont, bordas)
    return saida


# ---------------------------------------------------------------- trechos confiáveis

def _linhas(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return []


def trechos_confiaveis(linha: LineString, pontos: list[tuple[Point, str, float]],
                       cfg: ConfigMascaras) -> list[LineString]:
    """Pedaços de `linha` atribuídos a pontos confiáveis (regra 1). `pontos`: (ponto, status, confiança)."""
    if len(pontos) < 2 or linha.length == 0:
        return []
    pos = np.array([linha.project(p) for p, _, _ in pontos])
    ordem = np.argsort(pos)
    pos = pos[ordem]
    ruim = np.array([not (pontos[i][1] == "detectado" and pontos[i][2] >= cfg.limiar_confianca_pseudo)
                     for i in ordem])
    k = cfg.vizinhos_excluidos
    n = len(pos)
    ok = np.zeros(n, dtype=bool)
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        ok[i] = not ruim[lo:hi].any()
    meios = (pos[:-1] + pos[1:]) / 2.0
    ini = np.concatenate([[pos[0]], meios])
    fim = np.concatenate([meios, [pos[-1]]])
    pedacos = []
    i = 0
    while i < n:  # junta pontos confiáveis consecutivos num só pedaço
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        a, b = float(ini[i]), float(fim[j])
        if b > a:
            pedaco = substring(linha, a, b)
            if isinstance(pedaco, LineString) and pedaco.length > 0:
                pedacos.append(pedaco)
        i = j + 1
    return pedacos


@dataclass(frozen=True)
class GeometriasRotulo:
    faixa_cana: object  # polígono: faixa dos trechos confiáveis
    zona: object  # polígono: onde se rotula
    margem_todas: object  # polígono: faixa + margem de todas as fileiras detectadas
    comprimento_confiavel_m: float
    comprimento_total_m: float
    n_fileiras: int


def geometrias_da_deteccao(caminho_deteccao: Path, crs_ref, cfg: ConfigMascaras) -> GeometriasRotulo:
    """Lê `fileiras` e `trechos` do GeoPackage da detecção e monta as zonas das regras 1 a 3."""
    caminho_deteccao = Path(caminho_deteccao)
    if not caminho_deteccao.is_file() or caminho_deteccao.suffix.lower() != ".gpkg":
        raise ErroLeitura(f"GeoPackage da detecção não encontrado: {caminho_deteccao}")
    try:
        fileiras = gpd.read_file(caminho_deteccao, layer="fileiras")
        trechos = gpd.read_file(caminho_deteccao, layer="trechos")
    except Exception as exc:  # pyogrio levanta tipos variados
        raise ErroLeitura(f"{caminho_deteccao} sem as camadas 'fileiras' e 'trechos' da detecção: {exc}") from exc
    for nome, gdf, campos in (("fileiras", fileiras, ("id_fileira",)),
                              ("trechos", trechos, ("id_fileira", "status", "confianca"))):
        faltam = [c for c in campos if c not in gdf.columns]
        if faltam:
            raise ErroLeitura(f"camada {nome} de {caminho_deteccao} sem o(s) campo(s) {faltam}: "
                              "use o GeoPackage gravado por `python -m deteccao_linhas detectar`")
    verificar_crs({"ortomosaico": crs_ref, "fileiras": fileiras.crs, "trechos": trechos.crs})
    por_fileira: dict[str, list] = {}
    for _, t in trechos.iterrows():
        por_fileira.setdefault(str(t["id_fileira"]), []).append((t.geometry, str(t["status"]), float(t["confianca"])))
    confiaveis, todas = [], []
    for _, f in fileiras.iterrows():
        for linha in _linhas(f.geometry):
            todas.append(linha)
            confiaveis += trechos_confiaveis(linha, por_fileira.get(str(f["id_fileira"]), []), cfg)
    if not todas:
        raise ErroContrato(f"nenhuma fileira em {caminho_deteccao}")
    meia = cfg.largura_faixa_m / 2.0
    u_conf = unary_union(confiaveis) if confiaveis else None
    vazio = box(0, 0, 0, 0).buffer(0)
    return GeometriasRotulo(
        faixa_cana=u_conf.buffer(meia, cap_style="flat") if u_conf is not None else vazio,
        zona=u_conf.buffer(cfg.meia_largura_zona_m, cap_style="flat") if u_conf is not None else vazio,
        margem_todas=unary_union(todas).buffer(meia + cfg.margem_faixa_m),
        comprimento_confiavel_m=float(sum(c.length for c in confiaveis)),
        comprimento_total_m=float(sum(t.length for t in todas)),
        n_fileiras=len(fileiras),
    )


# ---------------------------------------------------------------- correção manual

def ler_correcoes(caminho: Path | None, crs_ref) -> list[tuple[object, int]]:
    """Polígonos de correção manual: (geometria, código). `classe` aceita código (0 a 4) ou nome."""
    if caminho is None:
        return []
    gdf = ler_vetor(caminho, "correções manuais")
    if CAMPO_CLASSE not in gdf.columns:
        raise ErroLeitura(f"correções manuais sem o campo '{CAMPO_CLASSE}' em {caminho}")
    verificar_crs({"ortomosaico": crs_ref, "correcoes": gdf.crs})
    por_nome = {v: k for k, v in NOMES_CLASSES.items()}
    saida = []
    for i, linha in gdf.iterrows():
        bruto = linha[CAMPO_CLASSE]
        geom = linha.geometry
        if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ErroContrato(f"correção {i}: geometria vazia ou não poligonal")
        if isinstance(bruto, str) and bruto.strip().lower() in por_nome:
            codigo = por_nome[bruto.strip().lower()]
        else:
            try:
                codigo = int(bruto)
            except (TypeError, ValueError):
                codigo = -1
        if codigo not in NOMES_CLASSES:
            raise ErroContrato(f"correção {i}: classe {bruto!r} inválida; use 0 a 4 ou {list(por_nome)}")
        saida.append((geom, codigo))
    return saida


# ---------------------------------------------------------------- regra por pixel

def rotular_janela(bandas: np.ndarray, valido: np.ndarray, limiar: np.ndarray, na_zona: np.ndarray,
                   na_faixa: np.ndarray, na_margem: np.ndarray, cfg: ConfigMascaras) -> np.ndarray:
    """Regras 2 a 4 numa janela. `limiar` é o limiar de ExG de cada pixel (NaN fora dos talhões)."""
    exg = exg_normalizado(bandas)
    ok = valido & na_zona & np.isfinite(limiar) & np.isfinite(exg)
    with np.errstate(invalid="ignore"):
        verde = exg >= limiar
    rot = np.full(valido.shape, IGNORADO, dtype=np.uint8)
    rot[ok & ~verde] = FUNDO
    if cfg.sombra_brilho_max > 0:
        escuro = bandas.mean(axis=0) < cfg.sombra_brilho_max
        rot[ok & ~verde & escuro] = SOMBRA
    if cfg.daninha_por_posicao:
        rot[ok & verde & ~na_margem] = DANINHA
    rot[ok & verde & na_faixa] = CANA
    return rot


def gerar_pseudo_rotulos(caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_deteccao: Path,
                         caminho_saida: Path, cfg: ConfigMascaras,
                         caminho_correcoes: Path | None = None) -> ResumoPseudoRotulos:
    """Grava o GeoTIFF de rótulos (uint8, códigos da seção 3) e, ao lado, o resumo em JSON."""
    orto = Ortomosaico(caminho_ortomosaico, cfg.bandas_rgb, cfg.resolucao_trabalho_m)
    try:
        talhoes = ler_talhoes(caminho_talhoes, cfg.campo_id_talhao, cfg.buffer_interno_m, orto.crs)
        geo = geometrias_da_deteccao(caminho_deteccao, orto.crs, cfg)
        correcoes = ler_correcoes(caminho_correcoes, orto.crs)
        print(f"Otsu do ExG por talhão ({len(talhoes.ids)} talhões)...", flush=True)
        limiares = limiares_otsu(orto, talhoes.ids, talhoes.poligonos_util, cfg)
        g = orto.grade
        cont = np.zeros(len(NOMES_CLASSES), dtype=np.int64)
        alvo = unary_union([talhoes.uniao_util] + [c for c, _ in correcoes]).bounds
        with criar_geotiff(caminho_saida, g, orto.crs, "uint8", nodata=IGNORADO) as dst:
            for lin, col, h, w in g.janelas(alvo, cfg.lado_janela_px):
                dados, valido = orto.ler(lin, col, h, w)
                limiar = np.full((h, w), np.nan, dtype=np.float32)
                for ident, poli in zip(talhoes.ids, talhoes.poligonos_util):
                    limiar[mascara_poligono(poli, g, lin, col, h, w)] = limiares[ident]
                rot = rotular_janela(
                    dados, valido, limiar,
                    mascara_poligono(geo.zona, g, lin, col, h, w),
                    mascara_poligono(geo.faixa_cana, g, lin, col, h, w),
                    mascara_poligono(geo.margem_todas, g, lin, col, h, w), cfg)
                if correcoes:
                    bx = box(*g.bounds_janela(lin, col, h, w))
                    formas = [(c.intersection(bx), v) for c, v in correcoes if c.intersects(bx)]
                    formas = [(f, v) for f, v in formas if not f.is_empty]
                    if formas:
                        # rasterize grava na ordem: o último polígono do arquivo prevalece
                        manual = rasterize(formas, out_shape=(h, w), transform=g.transform_janela(lin, col),
                                           fill=255, dtype="uint8")
                        sobre = (manual != 255) & valido
                        rot[sobre] = manual[sobre]
                cont += np.bincount(rot.ravel(), minlength=len(NOMES_CLASSES))[:len(NOMES_CLASSES)]
                dst.write(rot, 1, window=((lin, lin + h), (col, col + w)))
    finally:
        orto.fechar()
    resumo = ResumoPseudoRotulos(
        talhoes=list(talhoes.ids), limiar_exg_por_talhao=limiares, n_fileiras=geo.n_fileiras,
        comprimento_confiavel_m=geo.comprimento_confiavel_m, comprimento_total_m=geo.comprimento_total_m,
        n_poligonos_correcao=len(correcoes),
        pixels_por_classe={NOMES_CLASSES[k]: int(cont[k]) for k in NOMES_CLASSES})
    Path(caminho_saida).with_suffix(".json").write_text(
        json.dumps(asdict(resumo), ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo
