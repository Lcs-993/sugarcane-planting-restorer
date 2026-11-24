"""Configuração do pacote de máscaras. Todo valor numérico sem fonte lida é HIPÓTESE configurável
(docs/escopo-mascaras.md, seção 9.2). Premissa do projeto: faixa da fileira de 45 a 50 cm."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml

from .tipos import ErroConfig

ATRIBUTOS_VALIDOS = ("r", "g", "b", "exg", "gli")


@dataclass(frozen=True)
class ConfigMascaras:
    # Leitura
    bandas_rgb: tuple[int, int, int] = (1, 2, 3)  # numeração do rasterio, base 1
    resolucao_trabalho_m: float = 0.06  # HIPÓTESE; igual à da detecção (exigido pela FonteMascara)
    lado_janela_px: int = 1024  # gerência de memória, na resolução de trabalho; múltiplo de 256
    campo_id_talhao: str = "id"
    buffer_interno_m: float = 5.0  # HIPÓTESE; o mesmo da detecção

    # Atributos por pixel (nível 1). Todos HIPÓTESE (seção 7.1); GLI usado por Barrozo et al. (2025)
    atributos: tuple[str, ...] = ("r", "g", "b", "exg", "gli")
    raio_vizinhanca_px: int = 0  # HIPÓTESE; > 0 acrescenta média e desvio do ExG numa janela (2r+1)²

    # Modelo (nível 1). Random Forest como padrão: HIPÓTESE (Rocha, 2022, não achou diferença entre
    # CART, LDA e KNN para planta contra fundo; nenhuma fonte lida trata cana contra daninha)
    n_arvores: int = 100  # HIPÓTESE
    profundidade_max: int = 0  # HIPÓTESE; 0 = sem limite
    max_amostras_por_classe: int = 50000  # HIPÓTESE; amostragem estratificada no treino
    semente: int = 0
    n_jobs: int = -1

    # Pseudo-rótulos (seção 6). Tudo HIPÓTESE, menos a largura da faixa (premissa)
    limiar_confianca_pseudo: float = 0.70  # HIPÓTESE; trecho "detectado" abaixo disto fica ignorado
    vizinhos_excluidos: int = 1  # HIPÓTESE; pontos ao lado de um interpolado/duvidoso também ficam fora
    largura_faixa_m: float = 0.45  # premissa (45 a 50 cm); o mínimo, para o rótulo "cana" ser conservador
    margem_faixa_m: float = 0.20  # HIPÓTESE; perfilhamento além da faixa nominal: verde ali é ignorado
    meia_largura_zona_m: float = 0.75  # HIPÓTESE; só se rotula até esta distância do eixo de um trecho confiável
    sombra_brilho_max: float = 0.0  # HIPÓTESE; > 0 liga a regra: média RGB (0-255) abaixo disto e não verde -> sombra
    # Foco é identificar a cana (decisão de 2026-11-24). False: verde fora da faixa fica "ignorado" e a daninha
    # só entra por polígono manual. True: verde fora da faixa + margem vira "daninha" (regra original da seção 6);
    # na area_01 isso rotulou folha de cana como daninha.
    daninha_por_posicao: bool = False

    # Saída da classificação
    gravar_probabilidade_cana: bool = False

    def __post_init__(self) -> None:
        def erro(msg: str) -> None:
            raise ErroConfig(msg)

        if len(self.bandas_rgb) != 3 or any(int(b) < 1 for b in self.bandas_rgb):
            erro("bandas_rgb deve ter três números de banda (base 1).")
        for nome in ("resolucao_trabalho_m", "largura_faixa_m", "meia_largura_zona_m"):
            if not float(getattr(self, nome)) > 0:
                erro(f"{nome} deve ser > 0.")
        for nome in ("buffer_interno_m", "margem_faixa_m", "sombra_brilho_max"):
            if float(getattr(self, nome)) < 0:
                erro(f"{nome} deve ser >= 0.")
        if self.lado_janela_px < 256 or self.lado_janela_px % 256:
            erro("lado_janela_px deve ser múltiplo de 256 (blocos do GeoTIFF de saída).")
        if not self.atributos or any(a not in ATRIBUTOS_VALIDOS for a in self.atributos):
            erro(f"atributos deve conter só {list(ATRIBUTOS_VALIDOS)}.")
        if len(set(self.atributos)) != len(self.atributos):
            erro("atributos repetidos.")
        if self.raio_vizinhanca_px < 0 or self.raio_vizinhanca_px > 50:
            erro("raio_vizinhanca_px deve estar entre 0 e 50.")
        if self.n_arvores < 1 or self.profundidade_max < 0 or self.max_amostras_por_classe < 10:
            erro("n_arvores >= 1, profundidade_max >= 0 e max_amostras_por_classe >= 10.")
        if not 0.0 <= self.limiar_confianca_pseudo <= 1.0:
            erro("limiar_confianca_pseudo deve estar entre 0 e 1.")
        if self.vizinhos_excluidos < 0:
            erro("vizinhos_excluidos deve ser >= 0.")
        if self.meia_largura_zona_m <= self.largura_faixa_m / 2 + self.margem_faixa_m:
            erro("meia_largura_zona_m deve ser maior que largura_faixa_m/2 + margem_faixa_m "
                 "(senão não sobra zona para daninha e fundo).")


def carregar_config(caminho: Path | None) -> ConfigMascaras:
    """Lê YAML; None ou arquivo vazio devolve os padrões. Raises: ErroConfig."""
    if caminho is None:
        return ConfigMascaras()
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroConfig(f"arquivo de configuração não encontrado: {caminho}")
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ErroConfig(f"YAML inválido em {caminho}: {exc}") from exc
    if not bruto:
        return ConfigMascaras()
    if not isinstance(bruto, dict):
        raise ErroConfig(f"{caminho} deve conter um mapeamento chave: valor.")
    padrao = ConfigMascaras()
    conhecidas = {f.name for f in fields(ConfigMascaras)}
    desconhecidas = sorted(set(bruto) - conhecidas)
    if desconhecidas:
        raise ErroConfig(f"parâmetros desconhecidos na configuração: {', '.join(desconhecidas)}")
    valores = {}
    for nome, valor in bruto.items():
        ref = getattr(padrao, nome)
        if isinstance(ref, tuple):
            if not isinstance(valor, (list, tuple)):
                raise ErroConfig(f"{nome} deve ser uma lista, recebido {valor!r}.")
            tipo = type(ref[0])
            try:
                valores[nome] = tuple(tipo(v) for v in valor)
            except (TypeError, ValueError) as exc:
                raise ErroConfig(f"{nome} com valores inválidos: {valor!r}.") from exc
        elif isinstance(ref, bool):
            if not isinstance(valor, bool):
                raise ErroConfig(f"{nome} deve ser true ou false, recebido {valor!r}.")
            valores[nome] = valor
        elif isinstance(ref, int):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or int(valor) != valor:
                raise ErroConfig(f"{nome} deve ser inteiro, recebido {valor!r}.")
            valores[nome] = int(valor)
        elif isinstance(ref, float):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErroConfig(f"{nome} deve ser numérico, recebido {valor!r}.")
            valores[nome] = float(valor)
        else:
            if not isinstance(valor, str):
                raise ErroConfig(f"{nome} deve ser texto, recebido {valor!r}.")
            valores[nome] = valor
    return ConfigMascaras(**valores)
