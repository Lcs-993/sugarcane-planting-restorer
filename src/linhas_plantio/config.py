"""Configuração do motor. Todo valor sem fonte lida é HIPÓTESE configurável (docs/interfaces-fase1.md, seção 4)."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal

import yaml

from .tipos import ErroConfig

INDICES_VALIDOS = ("exg", "vari", "ndvi")


@dataclass(frozen=True)
class Config:
    # Índice de vegetação
    indice: Literal["exg", "vari", "ndvi"] = "exg"  # escolha de projeto, não validada
    bandas_rgb: tuple[int, int, int] = (1, 2, 3)  # numeração do rasterio, base 1
    banda_nir: int | None = None  # obrigatória se indice == "ndvi"

    # Estações e busca
    espacamento_estacoes_m: float = 10.0  # HIPÓTESE de partida do projeto
    semijanela_busca_m: float = 0.50  # HIPÓTESE de partida do projeto

    # Regras geométricas: valores de referência são premissas do projeto; tolerâncias são hipóteses
    espacamento_gemeas_ref_m: float = 1.50  # premissa do projeto
    tolerancia_espacamento_gemeas_m: float = 0.15  # HIPÓTESE, sem fonte lida
    largura_faixa_min_m: float = 0.45  # premissa do projeto
    largura_faixa_max_m: float = 0.50  # premissa do projeto
    tolerancia_largura_m: float = 0.10  # HIPÓTESE, sem fonte lida

    # Suavização e ruído
    janela_mediana: int = 3  # HIPÓTESE; em estações, ímpar
    limite_variacao_m: float = 0.30  # HIPÓTESE; entre estações vizinhas
    fator_spline: float = 0.0  # HIPÓTESE; 0 = spline interpolador, > 0 suaviza

    # Talhão e perfil
    buffer_interno_m: float = 5.0  # HIPÓTESE
    comprimento_amostra_m: float = 1.0  # HIPÓTESE; trecho longitudinal médio em cada ponto do perfil
    fracao_duvidosa_revisao: float = 0.30  # HIPÓTESE; limiar de revisão manual

    # Campos identificadores
    campo_id_talhao: str = "id"
    campo_id_passada: str = "id"

    def __post_init__(self) -> None:
        def erro(msg: str) -> None:
            raise ErroConfig(msg)

        if self.indice not in INDICES_VALIDOS:
            erro(f"indice inválido: {self.indice!r}. Use um de {INDICES_VALIDOS}.")
        if len(self.bandas_rgb) != 3 or any(int(b) < 1 for b in self.bandas_rgb):
            erro("bandas_rgb deve ter três números de banda (base 1).")
        if self.indice == "ndvi" and self.banda_nir is None:
            erro("indice 'ndvi' exige banda_nir (número da banda do infravermelho próximo).")
        if self.banda_nir is not None and int(self.banda_nir) < 1:
            erro("banda_nir deve ser >= 1 (base 1).")
        for nome in (
            "espacamento_estacoes_m",
            "semijanela_busca_m",
            "espacamento_gemeas_ref_m",
            "tolerancia_espacamento_gemeas_m",
            "largura_faixa_min_m",
            "largura_faixa_max_m",
            "tolerancia_largura_m",
            "limite_variacao_m",
            "comprimento_amostra_m",
        ):
            if not float(getattr(self, nome)) > 0:
                erro(f"{nome} deve ser > 0.")
        if self.largura_faixa_min_m > self.largura_faixa_max_m:
            erro("largura_faixa_min_m não pode ser maior que largura_faixa_max_m.")
        if self.janela_mediana < 1 or self.janela_mediana % 2 == 0:
            erro("janela_mediana deve ser um inteiro ímpar >= 1.")
        if self.fator_spline < 0:
            erro("fator_spline deve ser >= 0.")
        if self.buffer_interno_m < 0:
            erro("buffer_interno_m deve ser >= 0.")
        if not 0.0 <= self.fracao_duvidosa_revisao <= 1.0:
            erro("fracao_duvidosa_revisao deve estar entre 0 e 1.")


_TIPOS_NUMERICOS = {
    "espacamento_estacoes_m", "semijanela_busca_m", "espacamento_gemeas_ref_m",
    "tolerancia_espacamento_gemeas_m", "largura_faixa_min_m", "largura_faixa_max_m",
    "tolerancia_largura_m", "limite_variacao_m", "fator_spline", "buffer_interno_m",
    "comprimento_amostra_m", "fracao_duvidosa_revisao",
}


def carregar_config(caminho: Path | None) -> Config:
    """Lê YAML e devolve Config. None devolve os padrões.

    Raises:
        ErroConfig: chave desconhecida, tipo errado, valor fora de faixa, ndvi sem banda_nir,
            janela_mediana par.
    """
    if caminho is None:
        return Config()
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroConfig(f"arquivo de configuração não encontrado: {caminho}")
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ErroConfig(f"YAML inválido em {caminho}: {exc}") from exc
    if bruto is None:
        return Config()
    if not isinstance(bruto, dict):
        raise ErroConfig(f"{caminho} deve conter um mapeamento chave: valor.")
    conhecidas = {f.name for f in fields(Config)}
    desconhecidas = sorted(set(bruto) - conhecidas)
    if desconhecidas:
        raise ErroConfig(f"parâmetros desconhecidos na configuração: {', '.join(desconhecidas)}")
    valores = dict(bruto)
    for nome, valor in list(valores.items()):
        if nome in _TIPOS_NUMERICOS:
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErroConfig(f"{nome} deve ser numérico, recebido {valor!r}.")
            valores[nome] = float(valor)
        elif nome in ("janela_mediana",):
            if isinstance(valor, bool) or not isinstance(valor, int):
                raise ErroConfig(f"{nome} deve ser inteiro, recebido {valor!r}.")
        elif nome == "bandas_rgb":
            if not isinstance(valor, (list, tuple)) or len(valor) != 3:
                raise ErroConfig("bandas_rgb deve ser uma lista de três inteiros.")
            valores[nome] = tuple(int(v) for v in valor)
        elif nome == "banda_nir":
            if valor is not None and (isinstance(valor, bool) or not isinstance(valor, int)):
                raise ErroConfig(f"banda_nir deve ser inteiro ou nulo, recebido {valor!r}.")
        elif nome in ("campo_id_talhao", "campo_id_passada", "indice"):
            if not isinstance(valor, str):
                raise ErroConfig(f"{nome} deve ser texto, recebido {valor!r}.")
    return Config(**valores)
