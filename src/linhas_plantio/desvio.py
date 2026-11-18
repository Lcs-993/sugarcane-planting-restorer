"""Módulo desvio (skill ajuste-pente-gemeas): eixo do par e desvio lateral por estação
(docs/interfaces-fase1.md, seção 6.5).

Convenção do sinal: desvio_m é positivo quando o eixo real está à esquerda da linha projetada,
no sentido de digitalização. desvio_m = (t_esq + t_dir) / 2.
"""
from __future__ import annotations

from .config import Config
from .tipos import DeteccaoEstacao, EstacaoDesvio, Passada


def calcular_desvio_estacao(det: DeteccaoEstacao, talhao: str, cfg: Config) -> EstacaoDesvio:
    """Duas fileiras: desvio_m = (t_esq + t_dir)/2; espacamento_gemeas_m = t_esq - t_dir; status
    'detectado'. Uma fileira: desvio_m = t_esq - 0,75 (ou t_dir + 0,75), status 'estimado'.
    Nenhuma: desvio_m None, status 'duvidoso'. Não aplica tolerâncias (isso é da qualidade).

    O 0,75 m é metade de cfg.espacamento_gemeas_ref_m (premissa do projeto).
    """
    meio = cfg.espacamento_gemeas_ref_m / 2.0
    esq, dir_ = det.t_esq_m, det.t_dir_m
    if esq is not None and dir_ is not None:
        desvio, esp, status = (esq + dir_) / 2.0, esq - dir_, "detectado"
        conf = min(det.confianca_esq, det.confianca_dir)
    elif esq is not None:
        desvio, esp, status, conf = esq - meio, None, "estimado", det.confianca_esq
    elif dir_ is not None:
        desvio, esp, status, conf = dir_ + meio, None, "estimado", det.confianca_dir
    else:
        desvio, esp, status, conf = None, None, "duvidoso", 0.0
    return EstacaoDesvio(
        id_passada=det.id_passada, talhao=talhao, estacao_m=det.estacao_m, x=det.x, y=det.y,
        normal_esq=det.normal_esq, desvio_m=desvio, espacamento_gemeas_m=esp,
        largura_esq_m=det.largura_esq_m, largura_dir_m=det.largura_dir_m, status=status, confianca=conf,
    )


def calcular_desvios(passada: Passada, deteccoes: list[DeteccaoEstacao], cfg: Config) -> list[EstacaoDesvio]:
    """Aplica calcular_desvio_estacao a todas as estações da passada."""
    return [calcular_desvio_estacao(d, passada.talhao, cfg) for d in deteccoes]
