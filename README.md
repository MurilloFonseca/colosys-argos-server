# Back-end — Colosys Argos

FastAPI + MongoDB. Docs interativas em `http://localhost:8000/docs`.

## Rodando
Requisitos: [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
uv sync
cp .env.example .env            # preencha JWT_SECRET e as chaves das APIs
uv run fastapi dev
```

## Importando os GTFS (uma vez, e de vez em quando para atualizar)

Baixe os `.zip` manualmente ([SPTrans](https://www.sptrans.com.br/desenvolvedores/) exige login no portal; [ARTESP](https://dadosabertos.artesp.sp.gov.br/dataset/gtfs) está no portal de dados abertos; No repositório estão os dados baixados no dia 13/11/2026) e rode:

```bash
python -m app.gtfs_import sptrans caminho/gtfs_sptrans.zip
python -m app.gtfs_import artesp  caminho/gtfs_artesp.zip
```

O primeiro argumento é só um rótulo, usado como prefixo dos ids (`sptrans:3766-10`).
Reimportar uma fonte substitui os dados dela.

**Horários não são guardados.** O `stop_times.txt` é lido em streaming e cada linha vira *padrões*:
a sequência de paradas de um sentido + minutos médios desde a 1ª parada (coleção `padroes`).
Milhares de viagens idênticas viram um único documento. Também são guardados `linhas`, `paradas`
(com `zona`), `shapes`, `tarifas` (`fare_attributes`) e `regras_tarifa` (`fare_rules`).
A leitura é sequencial (pouca memória) quando o arquivo está agrupado por `trip_id`; se não estiver,
o importador detecta e usa um modo em memória, mais lento. Coleções de versões anteriores
(`horarios`, `viagens`, `calendarios`) são apagadas na importação.

## Endpoints

| Método | Rota | Auth | Para quê |
|---|---|---|---|
| POST | `/auth/registro`, `/auth/login` | – | devolvem `{access_token, usuario}` |
| GET | `/auth/me` | ✔ | usuário logado |
| GET | `/linhas?tipo=&q=&limite=&pular=` | – | `Linhas.jsx` (`tipo`: Metrô, Trem, Ônibus) |
| GET | `/linhas/{id}`, `/linhas/{id}/shape` | – | detalhe e traçado p/ o Leaflet |
| GET | `/linhas/{id}/paradas` | – | paradas em ordem por sentido, com minutos desde a 1ª |
| GET | `/linhas/{id}/tarifa` | – | tarifa(s) da linha (via `fare_rules`; sem regras, a tarifa única do feed) |
| GET | `/tarifas`, `/tarifas/{id}` | – | tarifas; o detalhe traz as regras |
| GET | `/buscar?q=` | – | sugestões (linhas + paradas) |
| GET | `/trajetos?origem=&destino=` | – | linhas diretas com duração estimada (`Rotas.jsx`) |
| GET | `/avisos` | – | `Avisos.jsx` |
| GET | `/onibus/linhas/{id}/posicoes` | – | ônibus ao vivo (Olho Vivo) |
| GET | `/onibus/paradas/{id}/previsao` | – | previsão de chegada (Olho Vivo) |
| GET | `/favoritos` | ✔ | `{linhas, trajetos}` |
| POST/DELETE | `/favoritos/linhas/{linha_id}` | ✔ | favoritar linha |
| POST/DELETE | `/favoritos/trajetos/{id}` | ✔ | favoritar trajeto |
| GET | `/relatos?linha_id=&transporte=` | – | `Relatos.jsx` |
| POST/DELETE | `/relatos/{id}` | ✔ | enviar/apagar relato (`FormularioRelato`) |

Rotas protegidas: header `Authorization: Bearer <token>`.

## Como funciona o "ao vivo"

- **API Trilhos**: se `TRILHOS_API_KEY` estiver definida, uma tarefa consulta a API a cada 6 min
  (o limite é 12 req/h) e guarda em `status_linhas`. Quando a situação de uma linha muda, cria um aviso.
  O status aparece no campo `status` de cada linha (casando `numero` da linha GTFS com o `codigo` do Trilhos).
- **Olho Vivo**: consultado sob demanda; o login/cookie é renovado automaticamente.
- Linhas sem fonte ao vivo (Metrô/CPTM hoje, e todos os ônibus) retornam `status: "Sem dados"`.

## Limitações conhecidas

- `/trajetos` só acha linhas **diretas** (sem baldeação) e **não tem horário de saída**, só duração
  estimada (média das viagens do GTFS, sem separar pico e vale). Para ônibus, use a previsão do Olho Vivo.
- Não existe "próximos horários programados": `calendar.txt`, `calendar_dates.txt` e `frequencies.txt` são ignorados.
- Regras de tarifa por zona (`origem_zona`/`destino_zona`) são só armazenadas e expostas; o back não calcula preço de um trajeto.
- Busca de paradas por nome é por trecho de texto (sem acento), limitada a 30 resultados.
