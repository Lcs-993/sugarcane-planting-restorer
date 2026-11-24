"""Configuração da detecção. TODO valor numérico sem fonte lida é HIPÓTESE configurável
(docs/escopo-deteccao.md, seção 6; tabela em docs/interfaces-deteccao.md, seção 4)."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal

import yaml

from .tipos import ErroConfig


@dataclass(frozen=True)
class Config:
    """Premissas do projeto: espaçamento 1,50 m e faixa de 45 a 50 cm. O resto é HIPÓTESE."""

    # Índice e binarização
    indice: Literal["exg", "vari"] = "exg"  # escolha de projeto, não validada
    variante_exg: Literal["normalizado", "bruto"] = "normalizado"  # HIPÓTESE
    bandas_rgb: tuple[int, int, int] = (1, 2, 3)  # numeração do rasterio, base 1
    resolucao_trabalho_m: float = 0.06  # HIPÓTESE; redução por média de área
    n_bins_otsu: int = 256  # HIPÓTESE
    buffer_interno_m: float = 5.0  # HIPÓTESE
    perfil_sobre: Literal["binario", "indice", "mascara"] = "binario"  # HIPÓTESE; "indice" não implementado
    # perfil_sobre="mascara": o perfil usa a máscara de classes (cana) do pacote mascaras em vez do ExG + Otsu
    # (docs/escopo-mascaras.md, seção 5). caminho_mascara: GeoTIFF de classes; também pode vir de --mascara.
    caminho_mascara: str | None = None

    # Orientação
    regiao_m: float = 150.0  # HIPÓTESE; lado das regiões de estimativa de direção
    area_minima_regiao_m2: float = 2000.0  # HIPÓTESE; regiões menores herdam direção (marcada)
    passo_angulo_grosso_graus: float = 1.0  # HIPÓTESE
    passo_angulo_fino_graus: float = 0.1  # HIPÓTESE
    sg_janela: int = 11  # HIPÓTESE; ímpar, em amostras do perfil de projeção
    sg_ordem: int = 3  # HIPÓTESE
    desvio_angular_max_graus: float = 15.0  # HIPÓTESE; contra a mediana das regiões vizinhas

    # Perfil lateral
    comprimento_bloco_m: float = 10.0  # HIPÓTESE central (H1)
    passo_bloco_m: float = 10.0  # HIPÓTESE; < comprimento_bloco_m gera sobreposição
    bin_lateral_m: float = 0.06  # HIPÓTESE
    subtrecho_m: float = 1.0  # HIPÓTESE; para a coerência longitudinal
    limiar_presenca_subtrecho: float = 0.10  # HIPÓTESE

    # Pente
    espacamento_fileiras_ref_m: float = 1.50  # premissa do projeto; referência com tolerância
    tolerancia_espacamento_m: float = 0.20  # HIPÓTESE
    semijanela_dente_m: float = 0.25  # HIPÓTESE
    dentes_por_janela_fase: int = 4  # HIPÓTESE
    proeminencia_min: float = 0.10  # HIPÓTESE; em fração de vegetação do perfil
    proeminencia_saturacao: float = 0.50  # HIPÓTESE (acrescentado); proeminência que dá contraste = 1
    largura_faixa_min_m: float = 0.45  # premissa do projeto
    largura_faixa_max_m: float = 0.50  # premissa do projeto
    tolerancia_largura_m: float = 0.15  # HIPÓTESE

    # Rastreamento
    tolerancia_ligacao_m: float = 0.30  # HIPÓTESE
    max_blocos_falha: int = 3  # HIPÓTESE
    comprimento_min_fileira_m: float = 30.0  # HIPÓTESE

    # Qualidade
    limiar_confianca: float = 0.50  # HIPÓTESE
    limite_variacao_m: float = 0.30  # HIPÓTESE; contra a mediana local, após remover a tendência
    janela_mediana: int = 3  # HIPÓTESE; em blocos, ímpar
    pesos_confianca: tuple[float, float, float, float] = (0.3, 0.3, 0.2, 0.2)  # HIPÓTESE (H5)
    # ordem dos pesos: contraste, coerência longitudinal, largura, ajuste ao pente

    campo_id_talhao: str = "id"

    # Fileiras em curva (ajustes de curva; docs/diagnostico-curvas.md). Tudo HIPÓTESE, sem fonte lida.
    # modo_blocos="regiao" reproduz o comportamento anterior (uma direção por região de regiao_m, blocos
    # retos, passo_bloco_m); para reproduzi-lo basta modo_blocos: regiao.
    # modo_blocos="faixas" estima um campo de direção em janelas pequenas e gera blocos ao longo de
    # linhas de corrente desse campo (faixas), cada bloco orientado pela direção local.
    modo_blocos: Literal["regiao", "faixas"] = "faixas"
    passo_bloco_faixas_m: float = 5.0  # HIPÓTESE; passo dos blocos no modo "faixas" (metade do comprimento: sobreposição)
    janela_direcao_m: float = 15.0  # HIPÓTESE; lado das janelas do campo de direção
    passo_angulo_grosso_campo_graus: float = 3.0  # HIPÓTESE; busca da direção nas janelas
    passo_angulo_fino_campo_graus: float = 0.5  # HIPÓTESE
    max_pontos_janela_direcao: int = 30000  # HIPÓTESE; subamostra por janela
    raio_suavizacao_direcao_m: float = 25.0  # HIPÓTESE; vizinhança do ajuste local do campo
    desvio_campo_max_graus: float = 8.0  # HIPÓTESE; janela que destoa do ajuste local é substituída por ele
    largura_corredor_m: float = 15.0  # HIPÓTESE; largura útil de cada faixa (blocos de uma linha de corrente)
    margem_lateral_bloco_m: float = 1.5  # HIPÓTESE; folga lateral lida mas não aceita (evita perder fileira na borda)
    curvatura_duvidosa_1_m: float = 0.04  # HIPÓTESE; 1/raio (raio de 25 m) acima do qual o trecho vira 'duvidoso' (0 = desligado)

    # DESVIOS das interfaces aprovadas: parâmetros acrescentados na implementação (todos HIPÓTESE)
    confianca_min_direcao: float = 0.15  # abaixo disto a região herda a direção das vizinhas
    sigma_suavizacao_perfil_m: float = 0.10  # suavização gaussiana do perfil lateral
    cobertura_min_bloco: float = 0.30  # fração mínima de pixels válidos para procurar fileiras
    max_pontos_orientacao: int = 200000  # limite de pontos na projeção por rotação (subamostra fixa)
    lateral_minima_bloco_m: float = 3.0  # bloco com extensão lateral menor é descartado
    distancia_min_picos_m: float = 0.40  # distância mínima entre picos do perfil
    distancia_fusao_picos_m: float = 0.90  # picos mais próximos que isto são fundidos (fica o mais proeminente)

    @property
    def passo_efetivo_m(self) -> float:
        """Distância entre blocos consecutivos no modo escolhido."""
        if self.modo_blocos == "faixas":
            return min(self.passo_bloco_faixas_m, self.comprimento_bloco_m)
        return self.passo_bloco_m

    @property
    def max_falhas_efetivas(self) -> int:
        """max_blocos_falha vale em múltiplos de passo_bloco_m; com passo menor, mantém o mesmo comprimento em metros."""
        return max(self.max_blocos_falha, int(round(self.max_blocos_falha * self.passo_bloco_m / self.passo_efetivo_m)))

    def __post_init__(self) -> None:
        def erro(msg: str) -> None:
            raise ErroConfig(msg)

        if self.indice not in ("exg", "vari"):
            erro(f"indice inválido: {self.indice!r}. Use 'exg' ou 'vari'.")
        if self.variante_exg not in ("normalizado", "bruto"):
            erro(f"variante_exg inválida: {self.variante_exg!r}.")
        if self.perfil_sobre == "indice":
            erro("perfil_sobre='indice' não foi implementado nesta versão; use 'binario' ou 'mascara'.")
        if self.perfil_sobre not in ("binario", "mascara"):
            erro(f"perfil_sobre inválido: {self.perfil_sobre!r}. Use 'binario' ou 'mascara'.")
        if self.perfil_sobre == "mascara" and not self.caminho_mascara:
            erro("perfil_sobre='mascara' exige caminho_mascara (ou a opção --mascara).")
        if len(self.bandas_rgb) != 3 or any(int(b) < 1 for b in self.bandas_rgb):
            erro("bandas_rgb deve ter três números de banda (base 1).")
        positivos = (
            "resolucao_trabalho_m", "regiao_m", "area_minima_regiao_m2", "passo_angulo_grosso_graus",
            "passo_angulo_fino_graus", "comprimento_bloco_m", "passo_bloco_m", "bin_lateral_m",
            "subtrecho_m", "espacamento_fileiras_ref_m", "tolerancia_espacamento_m",
            "semijanela_dente_m", "largura_faixa_min_m", "largura_faixa_max_m", "tolerancia_largura_m",
            "tolerancia_ligacao_m", "comprimento_min_fileira_m", "limite_variacao_m",
            "sigma_suavizacao_perfil_m", "max_pontos_orientacao", "lateral_minima_bloco_m",
            "distancia_min_picos_m", "distancia_fusao_picos_m", "desvio_angular_max_graus",
        )
        for nome in positivos:
            if not float(getattr(self, nome)) > 0:
                erro(f"{nome} deve ser > 0.")
        if self.n_bins_otsu < 8:
            erro("n_bins_otsu deve ser >= 8.")
        if self.buffer_interno_m < 0:
            erro("buffer_interno_m deve ser >= 0.")
        if self.sg_janela < 3 or self.sg_janela % 2 == 0:
            erro("sg_janela deve ser um inteiro ímpar >= 3.")
        if self.sg_ordem < 1 or self.sg_ordem >= self.sg_janela:
            erro("sg_ordem deve ser >= 1 e menor que sg_janela.")
        if self.modo_blocos not in ("regiao", "faixas"):
            erro(f"modo_blocos inválido: {self.modo_blocos!r}. Use 'regiao' ou 'faixas'.")
        for nome in ("janela_direcao_m", "passo_angulo_grosso_campo_graus", "passo_angulo_fino_campo_graus",
                     "max_pontos_janela_direcao", "raio_suavizacao_direcao_m", "desvio_campo_max_graus",
                     "largura_corredor_m", "passo_bloco_faixas_m"):
            if not float(getattr(self, nome)) > 0:
                erro(f"{nome} deve ser > 0.")
        if self.margem_lateral_bloco_m < 0 or self.curvatura_duvidosa_1_m < 0:
            erro("margem_lateral_bloco_m e curvatura_duvidosa_1_m devem ser >= 0.")
        if self.janela_mediana < 1 or self.janela_mediana % 2 == 0:
            erro("janela_mediana deve ser um inteiro ímpar >= 1.")
        if self.passo_bloco_m > self.comprimento_bloco_m:
            erro("passo_bloco_m não pode ser maior que comprimento_bloco_m (deixaria trechos sem leitura).")
        if self.largura_faixa_min_m > self.largura_faixa_max_m:
            erro("largura_faixa_min_m não pode ser maior que largura_faixa_max_m.")
        if self.dentes_por_janela_fase < 2:
            erro("dentes_por_janela_fase deve ser >= 2.")
        if self.max_blocos_falha < 0:
            erro("max_blocos_falha deve ser >= 0.")
        for nome in ("limiar_confianca", "limiar_presenca_subtrecho", "cobertura_min_bloco",
                     "confianca_min_direcao"):
            if not 0.0 <= float(getattr(self, nome)) <= 1.0:
                erro(f"{nome} deve estar entre 0 e 1.")
        if len(self.pesos_confianca) != 4 or any(p < 0 for p in self.pesos_confianca):
            erro("pesos_confianca deve ter quatro pesos >= 0.")
        if abs(sum(self.pesos_confianca) - 1.0) > 1e-6:
            erro("pesos_confianca devem somar 1.")
        if self.proeminencia_min <= 0:
            erro("proeminencia_min deve ser > 0.")
        if self.proeminencia_saturacao <= self.proeminencia_min:
            erro("proeminencia_saturacao deve ser maior que proeminencia_min.")


@dataclass(frozen=True)
class ConfigComparacao:
    """Hipóteses da comparação com a referência secundária (não é RTK)."""

    distancia_max_pareamento_m: float = 0.50  # HIPÓTESE; abaixo de metade do espaçamento
    campo_id_referencia: str | None = None
    usar_status: tuple[str, ...] = ("detectado", "interpolado")  # status nas estatísticas globais

    def __post_init__(self) -> None:
        if not float(self.distancia_max_pareamento_m) > 0:
            raise ErroConfig("distancia_max_pareamento_m deve ser > 0.")
        validos = {"detectado", "interpolado", "duvidoso"}
        if not self.usar_status or any(s not in validos for s in self.usar_status):
            raise ErroConfig(f"usar_status deve conter só {sorted(validos)}.")


def _ler_yaml(caminho: Path | None) -> dict | None:
    if caminho is None:
        return None
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroConfig(f"arquivo de configuração não encontrado: {caminho}")
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ErroConfig(f"YAML inválido em {caminho}: {exc}") from exc
    if bruto is None:
        return {}
    if not isinstance(bruto, dict):
        raise ErroConfig(f"{caminho} deve conter um mapeamento chave: valor.")
    return bruto


def _montar(classe, bruto: dict):
    padrao = classe()
    conhecidas = {f.name for f in fields(classe)}
    desconhecidas = sorted(set(bruto) - conhecidas)
    if desconhecidas:
        raise ErroConfig(f"parâmetros desconhecidos na configuração: {', '.join(desconhecidas)}")
    valores = {}
    for nome, valor in bruto.items():
        ref = getattr(padrao, nome)
        if isinstance(ref, tuple):
            if not isinstance(valor, (list, tuple)):
                raise ErroConfig(f"{nome} deve ser uma lista, recebido {valor!r}.")
            if nome == "usar_status":
                valores[nome] = tuple(str(v) for v in valor)
            else:
                try:
                    valores[nome] = tuple(type(ref[0])(v) for v in valor)
                except (TypeError, ValueError) as exc:
                    raise ErroConfig(f"{nome} com valores inválidos: {valor!r}.") from exc
        elif isinstance(ref, bool):
            raise ErroConfig(f"tipo não suportado em {nome}.")
        elif isinstance(ref, int):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or int(valor) != valor:
                raise ErroConfig(f"{nome} deve ser inteiro, recebido {valor!r}.")
            valores[nome] = int(valor)
        elif isinstance(ref, float):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErroConfig(f"{nome} deve ser numérico, recebido {valor!r}.")
            valores[nome] = float(valor)
        else:  # str ou None
            if valor is not None and not isinstance(valor, str):
                raise ErroConfig(f"{nome} deve ser texto, recebido {valor!r}.")
            valores[nome] = valor
    return classe(**valores)


def carregar_config(caminho: Path | None) -> Config:
    """Lê YAML. None devolve os padrões.

    Raises:
        ErroConfig: chave desconhecida, tipo errado, valor fora de faixa, sg_janela ou janela_mediana
            par, passo_bloco_m > comprimento_bloco_m, resolucao_trabalho_m <= 0, pesos que não somam 1,
            largura_faixa_min_m > largura_faixa_max_m.
    """
    bruto = _ler_yaml(caminho)
    return Config() if not bruto else _montar(Config, bruto)


def carregar_config_comparacao(caminho: Path | None) -> ConfigComparacao:
    """Idem, para ConfigComparacao. Raises: ErroConfig."""
    bruto = _ler_yaml(caminho)
    return ConfigComparacao() if not bruto else _montar(ConfigComparacao, bruto)
