"""Segmentação do ortomosaico em classes (docs/escopo-mascaras.md).

Pacote independente de `deteccao_linhas` e do QGIS. A ligação com a detecção é só pelo arquivo:
o GeoTIFF de classes que este pacote grava e que a detecção lê com `perfil_sobre: mascara`.
Nível 1 (classificador por pixel, scikit-learn). O nível 2 (U-Net em ONNX) não foi implementado:
só será desenvolvido se o nível 1 não separar daninha de cana (escopo, seção 2, item 3).
"""

__version__ = "0.2.0"
