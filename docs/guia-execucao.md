# Guia de execução (detecção de fileiras)

Como rodar a ferramenta `deteccao_linhas` por conta própria, no Windows, com três arquivos `.bat`.

**Aviso:** os `.bat` não foram testados no Windows (foram escritos e conferidos em Linux). O script Python que eles chamam (`scripts/rodar_area.py`) tem testes automatizados. Se algo falhar, a mensagem aparece na janela e fica em `log.txt`.

## 1. Instalar (uma vez)

Precisa do Python 3.10 ou mais novo instalado (marque "Add python.exe to PATH" na instalação). Depois, dê dois cliques em `scripts\instalar.bat`. Ele cria a pasta `.venv` e instala as dependências. Leva alguns minutos. Quem já tinha instalado antes da v0.2 deve rodar o `instalar.bat` de novo: entraram o scikit-learn e o joblib.

Se o computador tiver a variável `PROJ_LIB` apontando para outro programa (por exemplo, o PostGIS), o rasterio falha com "proj.db contains DATABASE.LAYOUT.VERSION.MINOR...". O `rodar_area.bat` limpa essa variável só na janela dele. Ao rodar comandos à mão, rode antes `set PROJ_LIB=` e `set PROJ_DATA=` na mesma janela.

## 2. Onde colocar os arquivos

Cada área (talhão ou fazenda a testar) tem uma pasta em `dados\areas\`. Já existem `area_01` e `area_02`. Para criar outra, dê dois cliques em `scripts\nova_area.bat` e digite o nome.

```
dados\areas\area_01\
  entrada\
    ortomosaico\   um GeoTIFF RGB (.tif)
    talhoes\       um .shp (com .shx, .dbf e .prj) ou .gpkg com os polígonos
                   (também vale o nome poligonos_talhoes\). O campo identificador é "id";
                   se for outro (ex.: CODE), crie config.yaml na área com campo_id_talhao: CODE
    referencia\    (opcional) um .shp ou .gpkg com linhas de referência, para comparar
                   (também vale o nome linhas_fileiras_cana_projetadas\)
    mds\           reservada para o teste opcional do modelo de terreno (ainda não é lida)
    mdt\           reservada para o mesmo teste (ainda não é lida)
    mascara\       (opcional) GeoTIFF de classes gerado por "python -m mascaras classificar"
                   (seção 5); se existir, o perfil das fileiras usa a classe cana dele
  saida\           os resultados; cada execução cria uma subpasta com data e hora
  config.yaml      (opcional) parâmetros da detecção desta área
```

Regras de cada pasta:
- Um arquivo só por pasta. Se houver mais de um, o script para e avisa.
- O ortomosaico e os talhões precisam estar no mesmo sistema de coordenadas projetado, em metros. Se estiverem diferentes, a ferramenta para com um erro dizendo quais, e não reprojeta.
- A camada de talhões precisa de um campo identificador chamado `id`.
- A camada de referência é opcional. Se existir, a ferramenta compara depois de detectar. A detecção nunca usa a referência.
- Os arquivos em `dados\` não vão para o Git: tudo lá é ignorado, menos os `.gitkeep`.

## 3. Rodar

Dê dois cliques em `scripts\rodar_area.bat` e digite o nome da área (por exemplo `area_01`). Ou, na linha de comando, com a pasta do projeto aberta:

```
scripts\rodar_area.bat area_01
```

## 4. O que sai

Em `dados\areas\<área>\saida\<data_hora>\`:
- `fileiras_detectadas.gpkg`: camadas `fileiras` e `trechos`.
- `relatorio_comparacao.json` e `diferencas.gpkg`: só se houver referência.
- `log.txt`: tudo o que apareceu na janela.

A comparação usa uma referência secundária, não é RTK, e não mede acurácia.

## Parâmetros

Por padrão usa `config_deteccao.yaml` na raiz. Para mudar numa área só, copie esse arquivo para `dados\areas\<área>\config.yaml` e edite. Todos os valores numéricos são hipóteses. Para a comparação existe `config_comparacao.yaml` na pasta da área, opcional.

## 5. Máscara de classes (opcional, v0.2)

Troca o ExG + Otsu por uma máscara que separa cana, daninha, fundo e sombra (docs/escopo-mascaras.md). É opcional: sem a pasta `entrada\mascara`, nada muda. Os comandos abaixo rodam na pasta do projeto, com o ambiente ativado (`.venv\Scripts\activate.bat`, e `set PROJ_LIB=` se for o caso da seção 1). Troque `<data_hora>` pela pasta da execução.

1. **Detecção atual** numa área de treino: `scripts\rodar_area.bat area_01`.
2. **Pseudo-rótulos** a partir dessa execução. `--correcoes` é opcional: polígonos desenhados no QGIS com um campo `classe` (`cana`, `daninha`, `fundo`, `sombra`, `ignorado`, ou os códigos 1, 2, 3, 4, 0). O último polígono do arquivo prevalece.
   ```
   python -m mascaras pseudo-rotulos --ortomosaico dados\areas\area_01\entrada\ortomosaico\orto.tif --talhoes dados\areas\area_01\entrada\talhoes\talhoes.gpkg --deteccao dados\areas\area_01\saida\<data_hora>\fileiras_detectadas.gpkg --correcoes correcoes_area_01.gpkg --saida dados\rotulos\area_01.tif --config config_mascaras.yaml
   ```
   Abra o `area_01.tif` no QGIS e confira. Ao lado sai o `area_01.json`, com o comprimento de fileira confiável e os pixels por classe.
3. **Treino**, uma vez, com várias áreas (repita `--par`):
   ```
   python -m mascaras treinar --par <orto_area_01.tif> dados\rotulos\area_01.tif --par <orto_area_02.tif> dados\rotulos\area_02.tif --modelo dados\modelos\nivel1.joblib --config config_mascaras.yaml
   ```
4. **Classificação** de qualquer área, gravando a máscara em `entrada\mascara`:
   ```
   python -m mascaras classificar --ortomosaico <orto.tif> --talhoes <talhoes.gpkg> --modelo dados\modelos\nivel1.joblib --saida dados\areas\area_03\entrada\mascara\mascara.tif --config config_mascaras.yaml
   ```
5. **Detecção com a máscara**: `scripts\rodar_area.bat area_03`. A janela mostra "máscara de classes: mascara.tif".
6. (Opcional) **IoU por classe** contra polígonos de teste desenhados e revisados à mão, num talhão que não entrou no treino: `python -m mascaras avaliar --mascara <mascara.tif> --teste <teste.gpkg> --relatorio iou.json`. Não use pseudo-rótulo como teste.

Regras:
- `resolucao_trabalho_m` precisa ser igual em `config_mascaras.yaml` e na configuração da detecção (padrão 0,06 m). Se for diferente, a detecção para e avisa.
- Treino e teste nunca no mesmo talhão (docs/escopo-mascaras.md, seção 8).
- O arquivo `.joblib` é um pickle: só carregue modelos gerados por este projeto.
- O que decide se a máscara ajuda é a comparação da detecção (ExG + Otsu contra máscara) com a referência de campo RTK, não o IoU.
