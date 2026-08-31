# Scanner swing canadien — Trading en Action

Scanner quotidien couvrant aussi largement que possible les actions de la **TSX**, de la **TSX Venture**, de la **CSE** et de **Cboe Canada/NEO**, avec des données de prix Yahoo Finance.

Le programme recherche un repli dans une tendance haussière, puis une confirmation de reprise :

- prix au-dessus de l'EMA50 et EMA50 au-dessus de l'EMA200;
- rebond récent sur EMA9, EMA20 ou EMA50;
- RSI qui se redresse après un repli;
- croisement haussier optionnel du Stoch RSI;
- retournement Heikin-Ashi rouge vers vert;
- clôture réelle au-dessus du sommet réel précédent;
- structure Higher Low ou cassure d'un pivot;
- volume et bandes de Bollinger utilisés comme confirmations;
- ATR pour calculer le stop et les objectifs.

Le MACD et l'EMA100 sont calculés et affichés, mais ne sont pas des conditions obligatoires puisqu'ils recoupent largement les informations déjà fournies par les autres moyennes et oscillateurs.

## Installation locale

Python 3.11 ou plus récent est recommandé.

```bash
python -m venv .venv
```

Windows :

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python -m scanner.main
```

macOS/Linux :

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m scanner.main
```

Les résultats sont écrits dans `output/` :

- `signaux_canada.csv` : tous les candidats au-dessus du score minimal;
- `top_signaux_canada.csv` : meilleurs candidats;
- `rapport_canada.md` : rapport lisible;
- `univers_canada.csv` : univers réellement utilisé;
- `scan_diagnostics.json` : erreurs, titres téléchargés et couverture obtenue.

## Univers canadien

Le programme interroge le répertoire officiel TMX pour la TSX et la TSXV, puis complète l'univers CSE et Cboe Canada/NEO avec le répertoire d'actions de Yahoo Finance. Il tente également de lire le répertoire public de la CSE. Ensuite, il :

1. fusionne les sources;
2. élimine les doublons;
3. exclut les instruments non désirés lorsque leur type est identifiable;
4. convertit les symboles vers Yahoo Finance (`.TO`, `.V`, `.CN`, `.NE`);
5. sauvegarde la dernière liste valide dans `cache/universe_cache.csv`;
6. fusionne, s'il existe, `data/custom_symbols.csv`.

La structure des sites boursiers peut changer. Si une source officielle devient inaccessible, le cache est utilisé et le rapport affiche clairement sa provenance. Un scan sans univers valide échoue au lieu de produire un rapport vide trompeur.

Le fichier facultatif `data/custom_symbols.csv` accepte :

```csv
symbol,exchange,name
WCP,TSX,Whitecap Resources
PNG,TSXV,Kraken Robotics
YOUR,CSE,Your Company
AMZN,NEO,Amazon CDR
```

Il est aussi possible d'inscrire directement un symbole Yahoo (`WCP.TO`) dans la colonne `symbol`.

## Configuration

Tous les paramètres se trouvent dans `config.yml`. Les plus importants sont :

- `minimum_score` : score minimal, sur 100;
- `top_n` : nombre de résultats dans le rapport principal;
- `require_trend` : impose `Close > EMA50 > EMA200`;
- `market_filter.enabled` : exige que XIC soit au-dessus de son EMA200;
- `download.batch_size` : réduire si Yahoo refuse certains lots;
- `universe.exchanges` : choisir TSX, TSXV, CSE et/ou NEO.

## Discord

La publication est facultative. Définir la variable d'environnement :

```text
DISCORD_WEBHOOK_URL
```

Le webhook ne doit jamais être écrit dans le code ni dans `config.yml`.

## GitHub Actions

Le workflow `.github/workflows/scan.yml` s'exécute du lundi au vendredi après la clôture. Dans un dépôt privé :

1. ajouter `DISCORD_WEBHOOK_URL` dans **Settings → Secrets and variables → Actions**;
2. activer GitHub Actions;
3. déclencher une première exécution manuelle avec **Run workflow**;
4. vérifier l'artifact `scanner-canada-results`.

Le programme utilise Yahoo Finance comme source pratique de données quotidiennes. Yahoo Finance n'est pas un flux officiel de marché et ne devrait pas servir à déclencher automatiquement des ordres réels.

## Lecture du score

| Composante | Points |
|---|---:|
| Tendance EMA50/EMA200 | 20 |
| Rebond EMA9/20/50 | 15 |
| RSI en redressement | 15 |
| Croisement Stoch RSI | 5 |
| Heikin-Ashi rouge vers vert | 10 |
| Clôture au-dessus du sommet précédent | 15 |
| Higher Low ou cassure de pivot | 10 |
| Volume supérieur à la moyenne 20 jours | 5 |
| Réintégration dans les Bollinger | 5 |

Le score sert à classer des configurations techniques; ce n'est ni une recommandation ni une garantie de rendement.
