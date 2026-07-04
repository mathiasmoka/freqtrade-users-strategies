# Plan d’automatisation Freqtrade

## Objectif

Construire un système local pour :

1. inventorier des dizaines de stratégies Freqtrade,
2. exécuter automatiquement des backtests,
3. lancer l’hyperopt stratégie par stratégie avec des paramètres adaptés,
4. relancer des backtests avec les meilleurs paramètres,
5. comparer les résultats spot et futures,
6. exposer les résultats dans un dashboard local.

L’idée n’est pas seulement de tester des stratégies, mais de mettre en place un pipeline reproductible qui permet de refaire les expériences proprement à chaque modification.

## Principe général

Le projet doit fonctionner comme une chaîne d’expérimentation :

`stratégie -> profil de config -> backtest initial -> hyperopt -> backtest final -> stockage -> comparaison -> dashboard`

Chaque stratégie doit être traitée comme une expérience paramétrée, pas comme un simple fichier Python isolé.
Le stockage des états et des résultats doit être incrémental afin que le dashboard reste exploitable pendant qu’un batch est encore en cours.
L’ensemble doit être exécutable dans Docker pour garantir la reproductibilité de l’environnement.

## Constat sur le repo actuel

Le dépôt contient :

- beaucoup de stratégies dans `Strategies/`,
- un dossier `Hyperopts/`,
- un fichier de config unique `Strategies/config (10).json`,
- des stratégies réparties entre plusieurs sous-dossiers.

Règles d’interprétation du dépôt :

- `Strategies/futures/` : stratégies futures,
- `Strategies/*.py` : stratégies spot par défaut,
- `Strategies/berlinguyinca/` : stratégies d’une source spécifique, spot par défaut,
- `Strategies/Ninja/` : stratégies d’une source spécifique, spot par défaut,
- `Strategies/lookahead_bias/` : stratégies d’une source spécifique, spot par défaut tant qu’aucune règle contraire n’est détectée.

Conséquence directe :

- l’inventaire ne doit pas seulement scanner des fichiers Python,
- il doit aussi capturer le `source_folder` et déduire un `market_type` initial à partir du chemin.

Cela implique trois besoins immédiats :

1. normaliser l’inventaire des stratégies,
2. séparer les configs sensibles et les profils d’exécution,
3. standardiser les résultats de backtest et d’hyperopt.

## Architecture cible

### 1. Couche d’inventaire

Rôle :

- scanner le dossier des stratégies,
- détecter le dossier source,
- détecter le type d’exécution attendu,
- enregistrer les métadonnées utiles,
- lier une stratégie à un profil de config.

Règles de détection recommandées :

1. si le fichier est sous `Strategies/futures/`, alors `market_type = futures`,
2. si le fichier est sous `Strategies/berlinguyinca/`, `Strategies/Ninja/` ou `Strategies/lookahead_bias/`, alors `market_type = spot` par défaut,
3. si le fichier est directement sous `Strategies/`, alors `market_type = spot`,
4. si une stratégie déclare explicitement une contrainte incompatible avec cette déduction, la règle explicite de la stratégie prend priorité,
5. le `source_folder` doit être conservé comme métadonnée pour filtrage et comparaison dans le dashboard.

Métadonnées à stocker par stratégie :

- nom de fichier,
- chemin absolu ou relatif canonique,
- classe de stratégie,
- `source_folder`,
- marché cible `spot` ou `futures`,
- timeframe principal,
- espaces d’hyperopt à optimiser,
- paires recommandées ou interdites,
- besoin de `protections`,
- besoin de `trailing stop`,
- complexité estimée,
- statut d’éligibilité au pipeline.

Sortie attendue :

- une base de métadonnées locale en SQLite,
- éventuellement un export `catalog.json` généré depuis SQLite.

### 2. Couche de configuration

Rôle :

- générer un `config` de base,
- spécialiser ce config par stratégie,
- séparer les paramètres communs des paramètres spécifiques,
- éviter de modifier manuellement un seul `config.json` pour tout le monde,
- produire un artefact de config versionné par run.

À prévoir :

- un `base_config` commun,
- un `profile_spot`,
- un `profile_futures`,
- un profil par exchange si nécessaire,
- un profil par stratégie si la stratégie impose des contraintes particulières.

Exemples de paramètres à rendre variables :

- `timeframe`,
- `stake_currency`,
- `trading_mode`,
- `margin_mode`,
- `leverage`,
- `pair_whitelist`,
- `pairlists`,
- `max_open_trades`,
- `protections`,
- `stoploss`,
- `position_adjustment_enable`,
- `use_custom_stoploss`,
- `ignore_buying_expired_candle_after`,
- `unfilledtimeout`.

Règle importante :

- le fichier de config ne doit pas contenir les secrets en clair,
- les clés exchange et les tokens doivent être externalisés dans un `.env` ou un fichier local non versionné.

Décision d’implémentation :

- chaque run doit avoir son `resolved_config.json` écrit dans un dossier d’artefacts,
- le hash de ce fichier doit être stocké en base pour garantir la reproductibilité.

### 3. Couche d’orchestration

Rôle :

- lancer les commandes Freqtrade,
- chaîner les phases,
- gérer les retries,
- enregistrer les logs,
- permettre l’exécution en lot ou stratégie par stratégie,
- écrire l’état d’avancement en SQLite à chaque étape.

Workflow type :

1. découverte de la stratégie,
2. création du scénario de run,
3. écriture du run en statut `queued`,
4. validation de la stratégie,
5. génération de config,
6. écriture du run en statut `running`,
7. backtest de base,
8. persistance des métriques intermédiaires,
9. hyperopt,
10. persistance des meilleurs paramètres,
11. backtest final,
12. persistance des métriques finales,
13. écriture du run en statut `completed` ou `failed`,
14. comparaison avec les autres stratégies.

Cette couche peut être réalisée avec :

- un script Python d’orchestration,
- ou un petit moteur de jobs local,
- ou un ensemble de scripts CLI avec un fichier de runbook.

Décision recommandée :

- un orchestrateur Python unique est le meilleur point de départ,
- il doit encapsuler toutes les commandes Freqtrade et centraliser l’écriture en base.
- cet orchestrateur doit être exécuté dans un conteneur Docker dédié.

### 4. Couche résultats

Rôle :

- stocker les résultats dans un format exploitable,
- garder l’historique des runs,
- comparer facilement plusieurs exécutions d’une même stratégie,
- rendre immédiatement visibles les runs partiels dans le dashboard.

Stockage recommandé :

- SQLite comme stockage principal dès le départ,
- Postgres si le volume devient important,
- fichiers JSON/CSV exportables pour les analyses rapides.

Règle impérative :

- chaque phase importante doit déclencher un `commit` SQLite,
- le dashboard doit lire la base telle quelle sans attendre la fin du batch.

Données à enregistrer :

- stratégie,
- dossier source,
- mode `spot` ou `futures`,
- paire ou univers de paires,
- timeframe,
- période testée,
- phase courante,
- statut du run,
- paramètres finaux,
- gains/pertes,
- drawdown,
- sharpe,
- profit factor,
- winrate,
- nombre de trades,
- duration moyenne des trades,
- frais estimés,
- slippage estimé si disponible,
- version du code,
- timestamp du run.

Données supplémentaires à prévoir pour le temps réel :

- heure de début,
- heure de dernière mise à jour,
- message d’état court,
- chemin du log,
- progression estimée,
- code de retour de la commande si échec.

### 5. Couche dashboard

Rôle :

- visualiser les résultats,
- filtrer par stratégie, marché, timeframe, paire, période,
- comparer les runs,
- identifier les meilleures combinaisons,
- rester utile alors que toutes les stratégies ne sont pas encore terminées.

Fonctions minimales du dashboard :

- compteur `queued / running / completed / failed`,
- tableau comparatif des stratégies,
- classement par performance,
- vue détaillée d’une stratégie,
- comparaison spot vs futures,
- filtre par `source_folder`,
- comparaison par période,
- comparaison par paire,
- graphe d’évolution des equity curves,
- distribution des trades,
- vue des paramètres hyperopt retenus,
- vue des erreurs pour les stratégies échouées.

Technologies possibles :

- Streamlit pour aller vite,
- Plotly pour les graphiques,
- SQLite comme source de données au début.
- Docker et Docker Compose pour l’exécution locale.

Comportement temps réel attendu :

- le dashboard rafraîchit automatiquement la base toutes les quelques secondes,
- les runs incomplets apparaissent immédiatement,
- les métriques intermédiaires d’un backtest déjà fini doivent être visibles même si l’hyperopt du même run continue,
- une stratégie en échec ne doit pas bloquer l’affichage global.

## Stratégie d’automatisation de l’hyperopt

L’automatisation doit être plus intelligente qu’un simple `hyperopt` sur toutes les stratégies avec les mêmes espaces.

### Classification des stratégies

Chaque stratégie doit être classée selon :

- type de marché : spot ou futures,
- dossier source,
- famille d’indicateurs,
- présence de `buy`, `sell`, `stoploss`, `roi`, `trailing`,
- besoin de leverage,
- sensibilité au timeframe,
- complexité du paramètre space.

### Espaces d’optimisation

Ne pas hyper-optimiser aveuglément tous les espaces.

Définir un profil d’hyperopt par famille :

- `buy/sell` pour les stratégies simples,
- `buy/sell/roi/stoploss` pour les stratégies plus complètes,
- `trailing` seulement si la stratégie l’utilise réellement,
- `protections` uniquement si elles impactent fortement le comportement,
- `leverage` et paramètres futures pour les stratégies futures.

### Sélection dynamique des paramètres

Le système doit être capable de :

- détecter les paramètres exposés dans la classe de stratégie,
- choisir les espaces pertinents,
- injecter des contraintes selon le profil de marché,
- ignorer les paramètres inutiles pour éviter de sur-optimiser.

### Sélection de pairs

Comme certaines stratégies performent seulement sur certaines combinaisons de paires :

- il faut permettre des runs par univers de paires,
- il faut enregistrer les résultats par paire,
- il faut prévoir une phase de sélection automatique de pairs candidates.

Exemple de logique :

1. backtest global sur un univers large,
2. identification des paires les plus prometteuses,
3. rerun sur un sous-ensemble de paires,
4. comparaison finale.

Règle de persistance :

- chaque sous-expérience de sélection de paires doit être un run distinct en base,
- les liens parent/enfant entre runs doivent être conservés pour retracer la séquence de décision.

## Séparation spot / futures

Les stratégies spot et futures ne doivent pas partager exactement le même pipeline d’exécution.

### Spot

Points de contrôle :

- pas de leverage,
- gestion simple du stake,
- paires spot uniquement,
- config d’exchange adaptée.

### Futures

Points de contrôle :

- mode futures explicite,
- leverage configuré,
- gestion du margin mode,
- attention aux stoploss et au position sizing,
- séparation stricte des paires futures.

Conclusion pratique :

- chaque stratégie doit déclarer son `market_type`,
- le générateur de config doit partir de ce type pour construire le bon profil.

Convention de fallback :

- si aucune déclaration explicite n’existe, le chemin du fichier reste la source de vérité initiale.

## Pipeline recommandé

### Phase 1 - Inventaire

Créer un catalogue des stratégies avec :

- nom,
- dossier source,
- type,
- espaces hyperopt,
- contraintes,
- statut.

### Phase 2 - Génération de config

Générer automatiquement un config par scénario :

- stratégie A en spot,
- stratégie A en futures,
- stratégie B avec univers restreint,
- stratégie C avec timeframe différent.

### Phase 3 - Backtest initial

Lancer un backtest standard pour chaque scénario afin d’obtenir une baseline.

### Phase 4 - Hyperopt

Lancer l’hyperopt avec :

- le bon profil de marché,
- le bon timeframe,
- les bons espaces,
- le bon timerange,
- un budget d’epochs prédéfini.

### Phase 5 - Backtest final

Appliquer les meilleurs paramètres et rerun un backtest reproductible.

### Phase 6 - Stockage

Enregistrer :

- résultats,
- paramètres,
- logs,
- version du code,
- config utilisée,
- statuts intermédiaires,
- métriques intermédiaires.

### Phase 7 - Dashboard

Afficher :

- état global du batch,
- scores par stratégie,
- résultats partiels déjà disponibles,
- scores par marché,
- scores par dossier source,
- scores par paire,
- évolution temporelle,
- métriques de risque.

## Exécution Docker

Le projet doit être pensé dès le départ pour tourner via Docker et non comme un ensemble de scripts dépendant directement de la machine hôte.

### Objectifs Docker

- figer l’environnement Python et Freqtrade,
- éviter les écarts entre machine locale et runs futurs,
- simplifier le lancement du pipeline,
- exposer facilement le dashboard local,
- persister SQLite, logs et artefacts via volumes.

### Architecture Docker recommandée

Services recommandés :

- `runner` : exécute l’orchestrateur Python et les commandes Freqtrade,
- `dashboard` : exécute l’application Streamlit,
- optionnellement `scheduler` plus tard si l’on veut des batchs planifiés.

Volumes persistants :

- volume pour `experiments/database/`,
- volume pour `experiments/configs/`,
- volume pour `experiments/runs/`,
- volume pour `experiments/logs/`,
- volume éventuel pour les données Freqtrade si elles sont gérées par le projet.

Règles importantes :

- SQLite doit être stocké sur un volume persistant partagé entre `runner` et `dashboard`,
- le dashboard doit ouvrir SQLite en lecture seule,
- les chemins d’artefacts stockés en base doivent rester valides à l’intérieur des conteneurs.

### Choix d’implémentation recommandés

- utiliser `docker compose` pour le développement local,
- partir d’une image Freqtrade officielle ou d’une image custom basée dessus,
- ajouter l’orchestrateur et le dashboard dans l’image du projet ou dans deux images proches,
- monter le dépôt en volume en développement,
- exposer Streamlit sur un port local.

## Organisation des fichiers suggérée

```text
.
├── Strategies/
├── Hyperopts/
├── docker/
├── experiments/
│   ├── configs/
│   ├── database/
│   ├── runs/
│   ├── results/
│   └── logs/
├── dashboards/
├── scripts/
├── data/
└── plan.md
```

### Détails

- `experiments/configs/` : configs générés automatiquement,
- `experiments/database/` : base SQLite et migrations,
- `experiments/runs/` : sorties de backtests et d’hyperopt,
- `experiments/results/` : résultats consolidés,
- `docker/` : fichiers liés aux images et au `docker compose`,
- `scripts/` : orchestration et parsing,
- `dashboards/` : application de visualisation.

## Modèle de données minimal

Table `strategies` :

- `id`
- `name`
- `file_path`
- `source_folder`
- `market_type`
- `timeframe`
- `status`

Table `runs` :

- `id`
- `strategy_id`
- `parent_run_id`
- `run_type`
- `config_hash`
- `resolved_config_path`
- `timerange`
- `pairset`
- `phase`
- `started_at`
- `updated_at`
- `finished_at`
- `status`
- `status_message`
- `log_path`
- `exit_code`

Table `metrics` :

- `run_id`
- `metric_scope`
- `profit_total`
- `profit_abs`
- `drawdown`
- `sharpe`
- `sortino`
- `winrate`
- `profit_factor`
- `trade_count`
- `avg_trade_duration`

Table `parameters` :

- `run_id`
- `param_name`
- `param_value`

Table `artifacts` :

- `id`
- `run_id`
- `artifact_type`
- `file_path`
- `created_at`

Table `events` :

- `id`
- `run_id`
- `event_type`
- `message`
- `created_at`

Remarque de conception :

- `runs` contient l’état opérationnel,
- `metrics` contient les résultats analytiques,
- `events` sert de journal léger pour afficher la progression en temps réel dans le dashboard.

## Règles d’exécution

1. Une stratégie n’est lancée que si elle est compatible avec le profil choisi.
2. Un run doit toujours être traçable jusqu’au fichier source et au config utilisé.
3. Les secrets ne doivent jamais être committés.
4. Les résultats doivent rester comparables dans le temps.
5. Le pipeline doit tolérer l’échec d’une stratégie sans bloquer tout le lot.
6. SQLite est la source de vérité pour l’état des runs et pour l’affichage temps réel.
7. Toute écriture importante doit être persistée immédiatement après la fin d’une phase.

## Priorités de mise en œuvre

### Priorité 1

- inventaire des stratégies,
- détection fiable par dossier,
- normalisation des configs,
- base SQLite et schéma initial,
- runtime Docker,
- stockage des résultats,
- backtest automatisé.

### Priorité 2

- hyperopt automatisé par profil,
- distinction spot/futures,
- dashboard temps réel sur résultats partiels,
- suivi des paramètres optimaux.

### Priorité 3

- sélection automatique des paires,
- dashboard interactif,
- comparaison multi-périodes.

### Priorité 4

- optimisation avancée de l’orchestration,
- parallélisation contrôlée,
- scoring multi-objectifs.

## Critères de succès

Le projet est réussi si l’on peut :

- ajouter une nouvelle stratégie dans `Strategies/`,
- respecter automatiquement la logique des sous-dossiers,
- lancer un pipeline automatique,
- obtenir un `backtest` initial,
- exécuter un `hyperopt` adapté,
- lancer un second `backtest`,
- comparer le tout dans un dashboard avant même la fin du batch complet,
- filtrer les résultats spot et futures séparément,
- filtrer par dossier source,
- retrouver exactement la configuration d’un run passé.

## Risques principaux

- sur-optimisation des paramètres,
- comparaisons biaisées entre spot et futures,
- configs trop hétérogènes,
- explosion du nombre de runs,
- performances non reproductibles,
- qualité variable des stratégies du dépôt,
- données de marché incomplètes ou incohérentes,
- risque de divergence entre stratégie, config et univers de paires.

## Décision pratique recommandée

Commencer par un MVP simple :

1. inventaire automatique,
2. générateur de config par stratégie,
3. backtest automatisé,
4. stockage SQLite transactionnel,
5. dashboard Streamlit en lecture temps réel,
6. exécution complète via Docker Compose.

Ensuite seulement :

1. hyperopt massif,
2. sélection dynamique des paires,
3. optimisation spot/futures avancée,
4. parallélisation et industrialisation.

## Spécification prête pour implémentation par IA

### Décisions déjà prises

- langage principal : Python,
- stockage principal : SQLite,
- interface de visualisation : Streamlit,
- runtime local : Docker Compose,
- source de vérité des stratégies : arborescence du dossier `Strategies/`,
- convention de marché : `Strategies/futures/` = futures, le reste = spot par défaut,
- traitement incrémental : écriture en base après chaque étape significative.

### Composants à implémenter

1. `strategy_catalog`
   - scanne les fichiers `.py`,
   - déduit `source_folder`,
   - déduit `market_type`,
   - extrait la classe de stratégie,
   - enregistre ou met à jour `strategies` dans SQLite.

2. `config_builder`
   - charge un `base_config`,
   - applique les overrides spot ou futures,
   - applique les overrides spécifiques à la stratégie,
   - écrit un `resolved_config.json`,
   - retourne le hash et le chemin de l’artefact.

3. `runner`
   - crée un enregistrement `runs`,
   - lance backtest et hyperopt via Freqtrade,
   - parse les sorties,
   - met à jour `metrics`, `events` et `artifacts`,
   - gère les statuts `queued`, `running`, `completed`, `failed`.

4. `result_parser`
   - lit les fichiers JSON/CSV produits par Freqtrade,
   - transforme les résultats dans le schéma SQLite,
   - distingue métriques intermédiaires et finales.

5. `dashboard`
   - lit SQLite en lecture seule,
   - rafraîchit périodiquement l’affichage,
   - expose la progression du batch et les résultats partiels.

6. `docker_runtime`
   - définit les services `runner` et `dashboard`,
   - monte les volumes persistants,
   - expose les ports utiles,
   - garantit que SQLite et les artefacts sont partagés entre services.

### Contrats minimaux entre composants

- `strategy_catalog` écrit dans `strategies`,
- `config_builder` écrit dans `artifacts` et renseigne `runs.config_hash`,
- `runner` est le seul composant qui change le statut des runs,
- `result_parser` n’exécute aucune commande Freqtrade,
- `dashboard` ne modifie jamais SQLite,
- `docker_runtime` ne contient pas de logique métier mais doit garantir les volumes et chemins attendus.

### Artefacts attendus

- une base `experiments/database/results.sqlite`,
- un dossier `experiments/configs/`,
- un dossier `experiments/runs/`,
- un dossier `experiments/logs/`,
- une application `dashboards/` lisant directement SQLite,
- un ou plusieurs scripts CLI dans `scripts/`,
- un `docker-compose.yml`,
- au moins un `Dockerfile`.

### Critères d’acceptation pour l’IA

1. lancer l’inventaire remplit correctement SQLite avec la détection par dossier,
2. lancer un run crée immédiatement une ligne `runs`,
3. un backtest terminé apparaît dans le dashboard même si les autres runs continuent,
4. un hyperopt en échec marque uniquement le run concerné en `failed`,
5. le dashboard peut filtrer `spot`, `futures` et `source_folder`,
6. chaque run peut être relié à son config résolu et à son log,
7. le projet peut être lancé localement via Docker sans dépendre d’un environnement Python hôte.
