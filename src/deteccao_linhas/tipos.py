"""Erros e dataclasses compartilhadas (docs/interfaces-deteccao.md, seções 2 e 3.2)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from affine import Affine
from pyproj import CRS
from shapely.geometry import LineString, MultiPolygon, Polygon


class ErroDeteccaoLinhas(Exception):
    """Base dos erros da ferramenta."""


class ErroConfig(ErroDeteccaoLinhas):
    """Parâmetro ausente, desconhecido ou fora de faixa."""


class ErroLeitura(ErroDeteccaoLinhas):
    """Arquivo inexistente, formato, campo identificador ausente, caminho não gravável."""


class ErroCRS(ErroDeteccaoLinhas):
    """CRS ausente, não projetado em metros ou divergente."""


class ErroContrato(ErroDeteccaoLinhas):
    """Geometria de tipo errado, vazia ou inválida, id duplicado, banda inexistente."""


class ErroDeteccao(ErroDeteccaoLinhas):
    """Direção não estimável, talhão sem pixels válidos, nenhuma fileira detectada."""


Status = Literal["detectado", "interpolado", "duvidoso"]
STATUS_VALIDOS = ("detectado", "interpolado", "duvidoso")


@dataclass(frozen=True)
class Talhao:
    id: str
    poligono: Polygon | MultiPolygon


@dataclass(frozen=True)
class DadosEntrada:
    caminho_ortomosaico: Path
    crs: CRS
    talhoes: tuple[Talhao, ...]


@dataclass(frozen=True)
class JanelaRaster:
    valores: np.ndarray  # 2D; float32 (índice) ou bool (binário)
    validade: np.ndarray  # 2D bool; False em nodata ou fora do polígono útil
    transform: Affine


@dataclass(frozen=True)
class AreaTalhao:
    talhao: Talhao
    poligono_util: Polygon | MultiPolygon  # talhão com buffer interno negativo
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class DirecaoFileiras:
    azimute_graus: float  # [0, 180), a partir do norte, horário
    vetor: tuple[float, float]  # (ux, uy) unitário, sentido alinhado a u_ref
    confianca: float  # 0 a 1
    herdada: bool  # True se vinda de vizinhas (marcada, nunca silenciosa)


@dataclass(frozen=True)
class Regiao:
    id_regiao: str
    talhao: str
    poligono: Polygon | MultiPolygon  # recorte da área útil
    direcao: DirecaoFileiras | None  # None antes da estimativa


@dataclass(frozen=True)
class Bloco:
    id_bloco: str
    id_regiao: str
    origem: tuple[float, float]  # (x, y) do quadro local
    u: tuple[float, float]
    n: tuple[float, float]  # normal à esquerda de u
    s0_m: float  # início do bloco ao longo de u, no quadro da região
    comprimento_m: float
    t_min_m: float
    t_max_m: float
    s_global_m: float  # dot(centro - c_ref, u_ref); ordem de processamento
    # DESVIO das interfaces aprovadas: polígono do bloco (retângulo recortado pela região) em
    # coordenadas do mapa, para que blocos de regiões vizinhas não contem o mesmo pixel duas vezes.
    poligono: Polygon | MultiPolygon | None = None


@dataclass(frozen=True)
class PerfilLateral:
    bloco: Bloco
    t_m: np.ndarray  # centros dos bins laterais
    vegetacao: np.ndarray  # fração de vegetação integrada ao longo do bloco; NaN sem dado
    coerencia: np.ndarray  # fração de subtrechos com vegetação no bin (0 a 1); NaN sem dado
    cobertura: float  # fração do bloco com pixels válidos (0 a 1)


@dataclass(frozen=True)
class PosicaoFileira:
    id_bloco: str
    t_m: float  # no quadro local do bloco
    x: float
    y: float
    largura_m: float | None
    proeminencia: float
    coerencia: float
    ajuste_pente: float  # 0 a 1; 1 = dente na posição esperada do pente
    espacamento_vizinha_m: float | None  # à posição vizinha à esquerda; None na última
    salto: bool  # espaçamento fora da tolerância (típico entre passadas)
    confianca: float  # 0 a 1


@dataclass(frozen=True)
class ResultadoPente:
    bloco: Bloco
    posicoes: tuple[PosicaoFileira, ...]  # ordenadas por t crescente
    fase_m: float | None  # fase global do pente; None se não ajustável


@dataclass(frozen=True)
class PontoFileira:
    id_bloco: str
    x: float
    y: float
    posicao_m: float
    status: Status
    confianca: float


@dataclass(frozen=True)
class Trilha:
    """Sequência de posições ligadas entre blocos; ainda sem id e sem avaliação final."""

    pontos: tuple[PontoFileira, ...]


@dataclass(frozen=True)
class FileiraAvaliada:
    talhao: str
    geometria: LineString  # sentido de u_ref
    pontos: tuple[PontoFileira, ...]
    comprimento_m: float
    confianca_media: float
    frac_duvidosa: float


@dataclass(frozen=True)
class Fileira:
    id_fileira: str
    avaliada: FileiraAvaliada


@dataclass(frozen=True)
class ResumoDeteccao:
    talhao: str
    limiar_otsu: float
    n_regioes: int
    n_regioes_direcao_herdada: int
    n_blocos: int
    n_fileiras: int
    n_trilhas_descartadas: int  # abaixo de comprimento_min_fileira_m
    n_pontos_por_status: dict[str, int]
