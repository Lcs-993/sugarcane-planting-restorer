"""Etapa 2: separar cana de daninha dentro do verde, por objetos (docs/escopo-mascaras.md, seção 12).

Etapa 1 (vegetação): ExG normalizado >= Otsu do talhão, o mesmo critério dos pseudo-rótulos.
Etapa 2: o verde de cada janela é dividido em superpixels (SLIC) e cada superpixel recebe atributos de
cor, textura, forma e, opcionalmente, posição em relação às fileiras detectadas. Um classificador
treinado com amostras pontuais (cada ponto rotula o superpixel onde cai) decide cana ou daninha.
Tudo HIPÓTESE (M7): nenhuma fonte lida trata cana contra daninha.

As janelas seguem uma grade fixa (múltiplos de `lado_janela_px` a partir da origem da grade de trabalho)
e são lidas com uma borda (`halo_objetos_m`). Assim, o treino e a classificação segmentam exatamente
da mesma forma, e o superpixel cortado pela borda da janela tem os atributos calculados inteiro.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString, box
from skimage.segmentation import slic

from .atributos import exg_normalizado, gli
from .config import ConfigMascaras
from .pseudo_rotulos import limiares_otsu
from .raster import Grade, Ortomosaico, Talhoes, ler_talhoes, mascara_poligono, verificar_crs
from .tipos import ErroContrato, ErroLeitura

ATRIBUTOS_BASE = ["r", "g", "b", "exg", "gli", "desvio_exg", "desvio_cinza", "gradiente", "area_m2",
                  "alongamento"]
ATRIBUTOS_POSICAO = ["dist_media_m", "dist_min_m", "frac_faixa", "alinhamento"]
DIST_MAX_M = 1.5  # distância às fileiras é cortada aqui (e usada quando não há fileira na janela)


def nomes_atributos(usar_posicao: bool) -> list[str]:
    return ATRIBUTOS_BASE + (ATRIBUTOS_POSICAO if usar_posicao else [])


@dataclass
class ContextoArea:
    """Ortomosaico aberto, talhões, limiar de Otsu por talhão e fileiras detectadas (opcionais)."""

    orto: Ortomosaico
    talhoes: Talhoes
    limiares: dict[str, float]
    fileiras: gpd.GeoSeries | None

    def fechar(self) -> None:
        self.orto.fechar()


def ler_fileiras(caminho_deteccao: Path, crs_ref) -> gpd.GeoSeries:
    caminho_deteccao = Path(caminho_deteccao)
    if not caminho_deteccao.is_file():
        raise ErroLeitura(f"GeoPackage da detecção não encontrado: {caminho_deteccao}")
    try:
        f = gpd.read_file(caminho_deteccao, layer="fileiras")
    except Exception as exc:  # pyogrio levanta tipos variados
        raise ErroLeitura(f"{caminho_deteccao} sem a camada 'fileiras' da detecção: {exc}") from exc
    verificar_crs({"ortomosaico": crs_ref, "fileiras": f.crs})
    return f.geometry[~f.geometry.is_empty].reset_index(drop=True)


def abrir_contexto(caminho_ortomosaico: Path, caminho_talhoes: Path, caminho_deteccao: Path | None,
                   cfg: ConfigMascaras) -> ContextoArea:
    orto = Ortomosaico(caminho_ortomosaico, cfg.bandas_rgb, cfg.resolucao_trabalho_m)
    try:
        talhoes = ler_talhoes(caminho_talhoes, cfg.campo_id_talhao, cfg.buffer_interno_m, orto.crs)
        fileiras = ler_fileiras(caminho_deteccao, orto.crs) if caminho_deteccao is not None else None
        if cfg.usar_posicao and fileiras is None:
            raise ErroContrato("usar_posicao exige o GeoPackage da detecção (fileiras)")
        print(f"Otsu do ExG por talhão ({len(talhoes.ids)} talhões)...", flush=True)
        limiares = limiares_otsu(orto, talhoes.ids, talhoes.poligonos_util, cfg)
    except Exception:
        orto.fechar()
        raise
    return ContextoArea(orto=orto, talhoes=talhoes, limiares=limiares, fileiras=fileiras)


def janelas_fixas(grade: Grade, bounds, lado: int) -> Iterator[tuple[int, int, int, int]]:
    """Janelas em múltiplos de `lado` a partir da origem da grade (mesmas no treino e na classificação)."""
    l0, c0, l1, c1 = grade.faixa_pixels(bounds)
    for lin in range((l0 // lado) * lado, l1, lado):
        for col in range((c0 // lado) * lado, c1, lado):
            yield lin, col, min(lado, grade.altura - lin), min(lado, grade.largura - col)


def janela_do_pixel(lin: int, col: int, grade: Grade, lado: int) -> tuple[int, int, int, int]:
    l0, c0 = (lin // lado) * lado, (col // lado) * lado
    return l0, c0, min(lado, grade.altura - l0), min(lado, grade.largura - c0)


@dataclass
class JanelaObjetos:
    lin: int
    col: int
    h: int
    w: int
    segmentos: np.ndarray  # (h, w) int32, rótulo do superpixel no núcleo da janela; 0 = não é verde
    ids: np.ndarray  # (n,) rótulos dos superpixels com pixel no núcleo
    X: np.ndarray  # (n, k) atributos, na ordem de nomes_atributos
    verde: np.ndarray  # (h, w) bool
    valido: np.ndarray  # (h, w) bool: pixel com dado e dentro da área útil de um talhão
    n_segmentos_total: int = 0
    avisos: list[str] = field(default_factory=list)


def _direcao_fileiras(linhas: list[LineString], janela) -> float | None:
    """Azimute (rad, eixo leste) predominante das fileiras na janela: média dos ângulos dobrados."""
    soma = np.zeros(2)
    for linha in linhas:
        trecho = linha.intersection(janela)
        partes = trecho.geoms if isinstance(trecho, MultiLineString) else [trecho]
        for p in partes:
            if not isinstance(p, LineString) or p.length == 0:
                continue
            xy = np.asarray(p.coords)
            d = np.diff(xy, axis=0)
            comp = np.hypot(d[:, 0], d[:, 1])
            ang = np.arctan2(d[:, 1], d[:, 0])
            soma += [(comp * np.cos(2 * ang)).sum(), (comp * np.sin(2 * ang)).sum()]
    if not soma.any():
        return None
    return 0.5 * math.atan2(soma[1], soma[0])


def processar_janela(ctx: ContextoArea, lin: int, col: int, h: int, w: int, cfg: ConfigMascaras,
                     usar_posicao: bool) -> JanelaObjetos:
    g = ctx.orto.grade
    halo = int(round(cfg.halo_objetos_m / g.res))
    dados, valido = ctx.orto.ler(lin, col, h, w, borda=halo)
    H, W = valido.shape
    L0, C0 = lin - halo, col - halo
    limiar = np.full((H, W), np.nan, dtype=np.float32)
    for ident, poli in zip(ctx.talhoes.ids, ctx.talhoes.poligonos_util):
        limiar[mascara_poligono(poli, g, L0, C0, H, W)] = ctx.limiares[ident]
    exg = exg_normalizado(dados)
    dentro = valido & np.isfinite(limiar) & np.isfinite(exg)
    with np.errstate(invalid="ignore"):
        verde = dentro & (exg >= limiar)
    nucleo = (slice(halo, halo + h), slice(halo, halo + w))
    nomes = nomes_atributos(usar_posicao)
    vazio = JanelaObjetos(lin, col, h, w, np.zeros((h, w), np.int32), np.zeros(0, np.int32),
                          np.zeros((0, len(nomes)), np.float32), verde[nucleo], dentro[nucleo])
    if not verde[nucleo].any():
        return vazio

    img = np.clip(dados / 255.0, 0, 1).transpose(1, 2, 0)
    # SLIC na janela toda e depois recortado pelo verde. Com mask=, o scikit-image 0.26 inicializa por k-means
    # e levou 442 s numa janela de 1024 px da area_01; assim leva ~1 s, e o superpixel mediano saiu 100% verde.
    px_seg = (cfg.tamanho_segmento_m / g.res) ** 2
    n_seg = max(1, int(verde.size / px_seg))
    seg = slic(img, n_segments=n_seg, compactness=cfg.compacidade_slic, start_label=1, channel_axis=-1)
    seg = np.where(verde, seg, 0).astype(np.int32)
    seg_nucleo = seg[nucleo]
    ids = np.unique(seg_nucleo[seg_nucleo > 0])
    if ids.size == 0:
        return vazio

    cinza = img.mean(axis=2)
    exg0 = np.nan_to_num(exg, nan=0.0)
    gli0 = np.nan_to_num(gli(dados), nan=0.0)
    grad = np.hypot(ndimage.sobel(cinza, axis=0), ndimage.sobel(cinza, axis=1))
    # o ndimage divide também para rótulos fora de `ids` (contagem zero) e avisa; os valores pedidos são finitos
    def media(a):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.asarray(ndimage.mean(a, seg, ids), dtype=np.float64)

    def desvio(a):
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.asarray(ndimage.standard_deviation(a, seg, ids), dtype=np.float64)
    n_px = np.asarray(ndimage.sum(np.ones_like(cinza), seg, ids))

    # momentos de segunda ordem: alongamento e orientação de cada superpixel
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    mx, my = media(xx), media(yy)
    cxx = media(xx * xx) - mx * mx
    cyy = media(yy * yy) - my * my
    cxy = media(xx * yy) - mx * my
    meio = (cxx + cyy) / 2
    raiz = np.sqrt(((cxx - cyy) / 2) ** 2 + cxy ** 2)
    l1, l2 = meio + raiz, np.maximum(meio - raiz, 0)
    alongamento = np.where(l1 > 0, 1 - np.sqrt(l2 / np.maximum(l1, 1e-12)), 0.0)
    theta_img = 0.5 * np.arctan2(2 * cxy, cxx - cyy)  # eixo x para leste, y para o sul
    theta_mapa = -theta_img  # ângulo com eixo leste, sentido anti-horário (norte para cima)

    colunas = {
        "r": media(img[..., 0]), "g": media(img[..., 1]), "b": media(img[..., 2]), "exg": media(exg0),
        "gli": media(gli0), "desvio_exg": desvio(exg0), "desvio_cinza": desvio(cinza), "gradiente": media(grad),
        "area_m2": n_px * g.res * g.res, "alongamento": alongamento,
    }
    if usar_posicao:
        janela_geo = box(*g.bounds_janela(L0, C0, H, W))
        linhas = []
        if ctx.fileiras is not None:
            idx = ctx.fileiras.sindex.query(janela_geo)
            linhas = [geo for geo in ctx.fileiras.iloc[idx] if geo.intersects(janela_geo)]
        if linhas:
            ras = rasterize([(geo, 1) for geo in linhas], out_shape=(H, W), transform=g.transform_janela(L0, C0),
                            fill=0, all_touched=True, dtype="uint8")
            dist = np.minimum(ndimage.distance_transform_edt(ras == 0) * g.res, DIST_MAX_M)
            theta_fil = _direcao_fileiras(linhas, janela_geo)
        else:
            dist = np.full((H, W), DIST_MAX_M)
            theta_fil = None
            vazio.avisos.append("janela sem fileira detectada")
        colunas["dist_media_m"] = media(dist)
        colunas["dist_min_m"] = np.asarray(ndimage.minimum(dist, seg, ids), dtype=np.float64)
        colunas["frac_faixa"] = media((dist <= cfg.largura_faixa_m / 2).astype(np.float64))
        colunas["alinhamento"] = (np.abs(np.cos(theta_mapa - theta_fil)) * alongamento
                                  if theta_fil is not None else np.zeros_like(alongamento))
    X = np.stack([colunas[n] for n in nomes], axis=1).astype(np.float32)
    return JanelaObjetos(lin, col, h, w, seg_nucleo, ids, X, verde[nucleo], dentro[nucleo],
                         n_segmentos_total=int(ids.size), avisos=vazio.avisos)
