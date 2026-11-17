"""Erros e tipos compartilhados entre os módulos do motor (docs/interfaces-fase1.md, seções 2.3 e 3.2)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import CRS
from shapely.geometry import LineString, MultiPolygon, Polygon


class ErroLinhasPlantio(Exception):
    """Base dos erros do projeto."""


class ErroConfig(ErroLinhasPlantio):
    """Parâmetro ausente, fora de faixa ou desconhecido."""


class ErroLeitura(ErroLinhasPlantio):
    """Arquivo inexistente, formato ou campo identificador ausente."""


class ErroCRS(ErroLinhasPlantio):
    """CRS divergente, ausente ou não projetado em metros."""


class ErroContrato(ErroLinhasPlantio):
    """Geometria de tipo errado, id duplicado, linha fora de talhão, banda inexistente."""


STATUS_VALIDOS = ("detectado", "estimado", "interpolado", "duvidoso")


@dataclass(frozen=True)
class Talhao:
    id: str
    poligono: Polygon | MultiPolygon


@dataclass(frozen=True)
class Passada:
    id_passada: str
    talhao: str  # id do talhão que contém a linha
    geometria: LineString  # sentido de digitalização preservado


@dataclass(frozen=True)
class DadosEntrada:
    caminho_ortomosaico: Path
    crs: CRS
    talhoes: tuple[Talhao, ...]
    passadas: tuple[Passada, ...]


@dataclass(frozen=True)
class JanelaRaster:
    valores: np.ndarray  # 2D; float32 (índice) ou bool (binário)
    validade: np.ndarray  # 2D bool; False onde não há dado (nodata) ou fora do polígono útil
    transform: Affine


@dataclass(frozen=True)
class AreaTalhao:
    talhao: Talhao
    poligono_util: Polygon | MultiPolygon  # talhão com buffer interno negativo
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class PerfilTransversal:
    t_m: np.ndarray  # coordenada transversal, positiva à esquerda
    valores: np.ndarray  # fração de vegetação (0 a 1) média em comprimento_amostra_m; NaN se sem dado


@dataclass(frozen=True)
class DeteccaoEstacao:
    id_passada: str
    estacao_m: float
    x: float
    y: float
    normal_esq: tuple[float, float]  # vetor unitário à esquerda da linha projetada
    t_esq_m: float | None  # centro da fileira esquerda; None se não encontrado
    t_dir_m: float | None
    largura_esq_m: float | None
    largura_dir_m: float | None
    confianca_esq: float  # 0 a 1
    confianca_dir: float


@dataclass(frozen=True)
class EstacaoDesvio:
    id_passada: str
    talhao: str
    estacao_m: float
    x: float
    y: float
    normal_esq: tuple[float, float]
    desvio_m: float | None  # bruto na detecção; None se nenhuma fileira detectada
    espacamento_gemeas_m: float | None
    largura_esq_m: float | None
    largura_dir_m: float | None
    status: str  # detectado | estimado | duvidoso (interpolado só após reconstrucao)
    confianca: float  # 0 a 1


@dataclass(frozen=True)
class ResultadoPassada:
    passada: Passada
    estacoes: tuple[EstacaoDesvio, ...]  # com desvio_m e status finais
    linha_corrigida: LineString
    frac_duvidosa: float
    frac_interpolada: float
    revisao_manual: bool
