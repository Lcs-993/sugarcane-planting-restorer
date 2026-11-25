# Guia de execução (detecção de fileiras)

Como rodar a ferramenta `deteccao_linhas` por conta própria, no Windows, com três arquivos `.bat`, e o fluxo da máscara de classes com o `mascaras.bat` (seção 5).

**Aviso:** `instalar.bat`, `nova_area.bat` e `rodar_area.bat` foram escritos e conferidos em Linux, sem teste no Windows. O `mascaras.bat` foi testado no Windows, pelo menu e por argumentos, com entrada redirecionada no lugar do teclado. Os scripts Python que eles chamam (`scripts/rodar_area.py` e `scripts/mascaras_area.py`) têm testes automatizados. Se algo falhar, a mensagem aparece na janela e fica em `log.txt`.

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
    mascara\       (opcional) GeoTIFF de classes gravado pelo passo "classificar" do
                   mascaras.bat (seção 5); se existir, o perfil das fileiras usa a classe cana dele
    correcoes_mascara\  (opcional) polígonos que corrigem os pseudo-rótulos (seção 5)
    teste_mascara\      (opcional) polígonos de teste desenhados à mão (seção 5)
  rotulos\         criada pelo passo "pseudo" do mascaras.bat
  saida\           os resultados; cada execução cria uma subpasta com data e hora
  config.yaml      (opcional) parâmetros da detecção desta área
  config_mascaras.yaml  (opcional) parâmetros das máscaras desta área; senão usa o da raiz
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

Troca o ExG + Otsu por uma máscara que separa cana, daninha, fundo e sombra (docs/escopo-mascaras.md). É opcional: sem arquivo em `entrada\mascara`, nada muda.

Use `scripts\mascaras.bat`. Com dois cliques, ele mostra um menu com os quatro passos e pergunta os nomes. Da linha de comando, passe o passo direto: `scripts\mascaras.bat pseudo area_01`. As áreas são as pastas de `dados\areas`; os modelos ficam em `dados\modelos\<nome>.joblib`.

1. **Detecção atual** numa área de treino: `scripts\rodar_area.bat area_01`, sem arquivo em `entrada\mascara`.
2. **Pseudo-rótulos**: `scripts\mascaras.bat pseudo area_01`. Usa a execução mais recente da detecção que não usou máscara. Grava `rotulos\rotulos.tif` e `rotulos\rotulos.json` (comprimento de fileira confiável e pixels por classe). Os dois arquivos são refeitos a cada vez. Abra o `.tif` no QGIS e confira.
   - Correções (opcional): um `.gpkg` ou `.shp` em `entrada\correcoes_mascara` com polígonos desenhados no QGIS e um campo `classe` (`cana`, `daninha`, `fundo`, `sombra`, `ignorado`, ou os códigos 1, 2, 3, 4, 0). O último polígono do arquivo prevalece. Depois de corrigir, rode o passo de novo.
3. **Treino**, uma vez, com várias áreas: `scripts\mascaras.bat treinar nivel1 area_01 area_02`. Grava `dados\modelos\nivel1.joblib`, o `.json` de metadados e o `nivel1_log.txt`.
4. **Classificação** de qualquer área: `scripts\mascaras.bat classificar area_03 nivel1`. Grava `entrada\mascara\mascara.tif`, substituindo a anterior. Se `gravar_probabilidade_cana: true`, a probabilidade vai para a pasta da execução em `saida\`, porque `entrada\mascara` só pode ter um arquivo.
5. **Detecção com a máscara**: `scripts\rodar_area.bat area_03`. A janela mostra "máscara de classes: mascara.tif". Para voltar ao ExG + Otsu, tire o arquivo de `entrada\mascara`.
6. (Opcional) **IoU por classe**: desenhe à mão polígonos de teste com o campo `classe` num talhão que não entrou no treino, ponha em `entrada\teste_mascara` e rode `scripts\mascaras.bat avaliar area_03`. O relatório sai em `saida\<data_hora>_mascaras_avaliar\relatorio_iou.json`. Não use pseudo-rótulo como teste.

Cada passo grava um `log.txt` em `saida\<data_hora>_mascaras_<passo>\`. O do treino fica ao lado do modelo.

Parâmetros: `config_mascaras.yaml` da raiz, ou o da pasta da área, se existir (passos pseudo e classificar, e treino com uma área só). O treino com várias áreas usa o da raiz. Em qualquer passo, `--config <arquivo>` no fim da linha passa por cima.

Regras:
- `resolucao_trabalho_m` precisa ser igual em `config_mascaras.yaml` e na configuração da detecção (padrão 0,06 m). Se for diferente, a detecção para e avisa.
- Treino e teste nunca no mesmo talhão (docs/escopo-mascaras.md, seção 8).
- O arquivo `.joblib` é um pickle: só carregue modelos gerados por este projeto.
- O que decide se a máscara ajuda é a comparação da detecção (ExG + Otsu contra máscara) com a referência de campo RTK, não o IoU.
- Para rodar os comandos à mão: `python -m mascaras --help` (ambiente ativado com `.venv\Scripts\activate.bat`, e `set PROJ_LIB=` se for o caso da seção 1).

### 5.1 Etapa 2: cana x daninha com amostras pontuais

Para separar cana de daninha, principalmente com daninha na entrelinha (docs/escopo-mascaras.md, seção 12). Não usa os pseudo-rótulos: aprende com pontos marcados por você.

1. **Pontos.** Ponha em `entrada\amostras_pontos` um GeoPackage de pontos com o campo `classe` (`cana` ou `daninha`) e marque um ponto no centro de cada touceira ou mancha. Privilegie os casos difíceis: daninha na entrelinha, daninha encostada na fileira, folha de cana avançando na entrelinha. Para a validação funcionar, precisa haver cana e daninha em pelo menos dois talhões.
2. **Detecção sem máscara** na área (`scripts\rodar_area.bat`), porque a posição em relação às fileiras é um dos atributos.
3. **Treino:** `scripts\mascaras.bat objetos-treinar objetos1 area_01`, ou o passo 5 do menu. A janela mostra o acerto de cana e de daninha com cada talhão deixado de fora, com e sem os atributos de posição.
4. **Classificação:** `scripts\mascaras.bat objetos-classificar area_01 objetos1`, ou o passo 6 do menu. Grava `entrada\mascara\mascara.tif`, que o `rodar_area.bat` passa a usar.
