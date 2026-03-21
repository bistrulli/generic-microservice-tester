# Fix: deploy_gen.py tronca le activity chain — model6 perde 2 servizi

## Problema

`tools/deploy_gen.py` genera il `LQN_TASK_CONFIG` per ogni task nel deploy.sh.
Per **model6_social_network**, il task `nginx_gateway` ha una chain nel GT:

```
gw_timeline → gw_call_tl (call timeline_service) → gw_call_ht (call home_timeline) → reply[GET_timeline]
```

Ma il deploy.sh generato produce solo:

```
gw_timeline → gw_call_tl (call timeline_service) → reply[GET_timeline]   ← STOP, manca gw_call_ht!
```

L'activity `gw_call_ht` (che chiama `home-timeline-svc/GET_home_timeline`) è **completamente assente**
dal JSON generato. Di conseguenza:
- `home_timeline` non riceve MAI traffico
- `social_graph` (chiamato da home_timeline) non riceve MAI traffico
- TLG trace discovery trova 10/12 servizi invece di 12/12

## File sorgente del bug

`tools/deploy_gen.py` — la funzione che converte le activity chain del modello LQN
in `LQN_TASK_CONFIG` JSON. Il bug è nella logica che cammina il grafo delle precedenze:
quando un'activity ha una call E un successore nella sequenza, il generatore mette il
reply sull'activity con la call e ignora il successore.

## Input di riferimento (GT .lqn)

File: `/Users/emilio-imt/git/TLG/tests/lqn_structure_test/model6_social_network/model6_social_network_gt.lqn`

Sezione nginx_gateway (linee 79-95):
```
A nginx_gateway
  s gw_call_compose 0.0001
  s gw_call_tl 0.0001
  s gw_call_ht 0.0001         ← activity mancante nel deploy generato
  s gw_compose 0.106
  s gw_timeline 0.015
  y gw_call_compose POST_create_post 1
  y gw_call_tl GET_user_timeline 1
  y gw_call_ht GET_home_timeline 1    ← call mancante nel deploy generato
  :
  gw_compose -> gw_call_compose;
  gw_timeline -> gw_call_tl;
  gw_call_tl -> gw_call_ht;          ← sequenza mancante nel deploy generato
  gw_call_compose[POST_compose]
  gw_call_ht[GET_timeline]            ← reply su gw_call_ht, non gw_call_tl
```

## Output attuale (deploy.sh generato, SBAGLIATO)

```json
{
  "task_name": "nginx_gateway",
  "entries": {
    "POST_compose": {"start_activity": "gw_compose"},
    "GET_timeline": {"start_activity": "gw_timeline"}
  },
  "activities": {
    "gw_call_compose": {"service_time": 0.0001, "sync_calls": {"compose-post-svc/POST_create_post": 1.0}},
    "gw_call_tl": {"service_time": 0.0001, "sync_calls": {"timeline-service-svc/GET_user_timeline": 1.0}},
    "gw_compose": {"service_time": 0.106},
    "gw_timeline": {"service_time": 0.015}
  },
  "graph": {
    "sequences": [["gw_compose","gw_call_compose"], ["gw_timeline","gw_call_tl"]],
    "replies": {"gw_call_compose": "POST_compose", "gw_call_tl": "GET_timeline"}
  }
}
```

Mancano: `gw_call_ht`, la sequenza `gw_call_tl → gw_call_ht`, e il reply è su `gw_call_tl` invece di `gw_call_ht`.

## Output atteso (CORRETTO)

```json
{
  "task_name": "nginx_gateway",
  "entries": {
    "POST_compose": {"start_activity": "gw_compose"},
    "GET_timeline": {"start_activity": "gw_timeline"}
  },
  "activities": {
    "gw_call_compose": {"service_time": 0.0001, "sync_calls": {"compose-post-svc/POST_create_post": 1.0}},
    "gw_call_tl": {"service_time": 0.0001, "sync_calls": {"timeline-service-svc/GET_user_timeline": 1.0}},
    "gw_call_ht": {"service_time": 0.0001, "sync_calls": {"home-timeline-svc/GET_home_timeline": 1.0}},
    "gw_compose": {"service_time": 0.106},
    "gw_timeline": {"service_time": 0.015}
  },
  "graph": {
    "sequences": [["gw_compose","gw_call_compose"], ["gw_timeline","gw_call_tl"], ["gw_call_tl","gw_call_ht"]],
    "replies": {"gw_call_compose": "POST_compose", "gw_call_ht": "GET_timeline"}
  }
}
```

## Come fixare

### Opzione A: Fix in deploy_gen.py (fix generico)

Trovare nel codice dove le activity chain vengono camminate per generare `sequences` e `replies`.
Il bug è che quando un'activity ha un sync_call, il generatore assume che sia l'ultima della chain
e ci mette il reply. Invece deve continuare a camminare i successori fino alla vera fine della chain
(l'activity con il reply marker `[entry_name]` nel .lqn).

### Opzione B: Fix solo nel deploy.sh generato (fix locale)

Modificare manualmente il JSON nella linea 93 del deploy.sh in
`/Users/emilio-imt/git/TLG/tests/lqn_structure_test/model6_social_network/deploy.sh`.

Fare le 3 modifiche descritte sopra.

## Come verificare

```bash
# 1. Rigenerare il deploy.sh dal GT
python tools/deploy_gen.py /Users/emilio-imt/git/TLG/tests/lqn_structure_test/model6_social_network/model6_social_network_gt.lqn -o /tmp/deploy_fixed.sh

# 2. Controllare che nginx_gateway abbia gw_call_ht
grep gw_call_ht /tmp/deploy_fixed.sh

# 3. Controllare che il JSON abbia 3 sequenze per nginx_gateway
grep -o '"sequences":\[[^]]*\]' /tmp/deploy_fixed.sh | head -1

# 4. Deployare e verificare che home_timeline riceva traffico
cd /Users/emilio-imt/git/TLG/tests/lqn_structure_test/model6_social_network/
./deploy.sh down && ./deploy.sh up
# Mandare qualche richiesta, poi:
curl http://localhost:16686/api/services | python3 -m json.tool | grep -E "home|social"
# Atteso: "home-timeline" e "social-graph" presenti

# 5. Validate con TLG (12/12 servizi attesi)
tlg validate-system . --use-gt-loadgen --calibrate-users 1 --validate-users 1 --load-duration 600
```

## Impatto

Questo bug potrebbe affliggere QUALSIASI modello LQN con chain di 3+ activity nella stessa entry
(activity → call_A → call_B → reply). I modelli con chain di max 2 (activity → call → reply) non
sono affetti.
