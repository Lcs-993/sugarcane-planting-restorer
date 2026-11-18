# Guia de execução (detecção de fileiras)

Como rodar a ferramenta `deteccao_linhas` por conta própria, no Windows, com três arquivos `.bat`.

**Aviso:** os `.bat` não foram testados no Windows (foram escritos e conferidos em Linux). O script Python que eles chamam (`scripts/rodar_area.py`) tem testes automatizados. Se algo falhar, a mensagem aparece na janela e fica em `log.txt`.

## 1. Instalar (uma vez)

Precisa do Python 3.10 ou mais novo instalado (marque "Add python.exe to PATH" na instalação). Depois, dê dois cliques em `scripts\instalar.bat`. Ele cria a pasta `.venv` e instala as dependências. Leva alguns minutos.

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
