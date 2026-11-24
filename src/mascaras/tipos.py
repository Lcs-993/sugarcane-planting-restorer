"""Classes da máscara, erros e metadados do modelo (docs/escopo-mascaras.md, seções 3 e 4)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Códigos da seção 3 do escopo. A detecção de linhas lê estes mesmos códigos do GeoTIFF.
IGNORADO, CANA, DANINHA, FUNDO, SOMBRA = 0, 1, 2, 3, 4
NOMES_CLASSES = {IGNORADO: "ignorado", CANA: "cana", DANINHA: "daninha", FUNDO: "fundo", SOMBRA: "sombra"}
CLASSES_TREINO = (CANA, DANINHA, FUNDO, SOMBRA)  # "ignorado" nunca é aprendido

VERSAO_FORMATO_MODELO = 1


class ErroMascaras(Exception):
    """Base dos erros do pacote."""


class ErroConfig(ErroMascaras):
    """Parâmetro ausente, desconhecido ou fora de faixa."""


class ErroLeitura(ErroMascaras):
    """Arquivo inexistente, formato não suportado, campo ausente, caminho não gravável."""


class ErroCRS(ErroMascaras):
    """CRS ausente, não projetado em metros ou divergente. Nada é reprojetado."""


class ErroContrato(ErroMascaras):
    """Geometria ou raster fora do contrato, modelo incompatível, rótulos sem amostras."""


@dataclass
class MetadadosModelo:
    """Arquivo JSON que acompanha o modelo (escopo, seção 4)."""

    nivel: int
    classes: dict[str, str]  # código -> nome, só as classes vistas no treino
    bandas_rgb: list[int]
    resolucao_trabalho_m: float
    atributos: list[str]
    raio_vizinhanca_px: int
    versao_pacote: str
    versao_sklearn: str
    areas_treino: list[str]  # caminhos dos rótulos usados
    talhoes_treino: list[str]
    amostras_por_classe: dict[str, int]
    criado_em: str
    parametros_modelo: dict = field(default_factory=dict)
    versao_formato: int = VERSAO_FORMATO_MODELO

    def gravar(self, caminho: Path) -> None:
        Path(caminho).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def ler(cls, caminho: Path) -> "MetadadosModelo":
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ErroLeitura(f"metadados do modelo não encontrados: {caminho}")
        try:
            bruto = json.loads(caminho.read_text(encoding="utf-8"))
            return cls(**bruto)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ErroContrato(f"metadados do modelo inválidos em {caminho}: {exc}") from exc


def caminho_metadados(caminho_modelo: Path) -> Path:
    """modelo.joblib -> modelo.json, ao lado."""
    return Path(caminho_modelo).with_suffix(".json")
