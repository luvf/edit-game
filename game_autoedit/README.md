# game_autoedit

Génération du fichier de cut d'une game par apprentissage, à partir de l'audio
des archives.

Le module est autonome : il lit la base et les médias, écrit uniquement dans son
cache, et rien dans l'application web ne dépend de lui. L'intégration au render
queue viendra plus tard.

## Principe

Le modèle voit 30 s d'audio et répond, tous les 80 ms, à trois questions :

| canal | question |
|---|---|
| `in` | un point commence-t-il ici ? |
| `out` | un point se termine-t-il ici ? |
| `inside` | sommes-nous à l'intérieur d'un point ? |

Les frontières sont des instants ; les labels ne valent qu'à la demi-seconde
près. La cible est donc étalée sur une fenêtre de tolérance dont la forme est un
paramètre (`--target-shape`). Le canal `inside` n'est pas une tâche auxiliaire :
savoir qu'un point est en cours est exactement ce qui distingue un coup de
sifflet de fin d'un coup de sifflet de début.

Le décodage (courbes → segments) est séparé du modèle : les seuils sont le
bouton qu'on tourne quand l'outil propose trop ou trop peu, et le tourner ne doit
pas demander de réentraîner.

## Utilisation

```bash
# état du dataset : couverture, distribution des labels, anomalies
python -m game_autoedit inspect [--warnings] [--rejected]

# extraction de l'audio des archives vers le cache local (une fois)
python -m game_autoedit build-cache
python -m game_autoedit cache-status

# partition train/val/test
python -m game_autoedit splits
python -m game_autoedit splits --holdout-tournament "XIII TNZ"

# entraînement
python -m game_autoedit train --name baseline --epochs 40

# évaluation sur des games entières, décodées
python -m game_autoedit evaluate --run baseline --part test --per-game

# génération d'un fichier de cut
python -m game_autoedit predict --run baseline --game 478
```

Le cache est jetable : `$GAME_AUTOEDIT_CACHE` (défaut
`/mnt/video/juggerData/cache_game_edit/`) peut être effacé et reconstruit
entièrement depuis la base et les archives.

## Tableau de bord

```bash
make autoedit-dashboard        # ou : uv run streamlit run game_autoedit/dashboard/app.py
```

Trois écrans :

- **Game** — le principal. On choisit un run et une game, et on voit les trois
  courbes de probabilité le long du temps, le montage humain et le montage
  proposé sur le même axe, et les seuils en pointillés. Les curseurs de
  décodage recalculent tout en direct, sans réentraîner ni recalculer les
  courbes. Un game du jeu de test affiche un avertissement : le regarder pour
  choisir un réglage revient à le brûler.
- **Runs** — comparaison de tous les entraînements, courbes de loss et d'AP par
  epoch, configuration complète de chacun.
- **Dataset** — couverture, distribution des labels par game, motifs
  d'exclusion.

## Construction du dataset

C'est le principal levier sur ce problème, donc chaque choix est une option
comparable plutôt qu'une valeur en dur.

| option | effet |
|---|---|
| `--sampling boundary\|uniform\|dense` | où sont tirées les fenêtres d'un epoch |
| `--positive-ratio` | part des fenêtres ancrées sur une vraie frontière |
| `--jitter` | de combien la frontière peut s'écarter du centre de la fenêtre |
| `--density` | fenêtres par minute de game |
| `--tolerance` | demi-largeur positive autour d'une frontière |
| `--target-shape rect\|triangle\|gaussian` | pondération dans cette fenêtre |
| `--window`, `--hop` | durée d'une fenêtre, pas de la grille de sortie |
| `--loss bce\|focal` | pondérer les positifs rares, ou atténuer les négatifs faciles |

Tirer uniformément dépense presque tout l'epoch sur du silence : une game porte
une frontière toutes les quarante secondes environ. `--sampling boundary` ancre
une part des fenêtres sur une frontière réelle et tire le reste au hasard comme
négatifs.

## Partition

Par défaut le tirage se fait **par game**. Pour mesurer la généralisation à des
conditions inédites — autre salle, autre public, autre position de caméra —
`--holdout-tournament` sort un ou plusieurs tournois de l'entraînement et en fait
le jeu de test.

## Sortie

`predict` écrit trois choses par game :

- `game_<id>_cut.json` — les `points` au format de l'application, en frames à la
  vraie cadence de l'archive ;
- un bloc `comment` dans ce même fichier — statistiques du montage produit, et
  une liste `review` des endroits à vérifier : segment anormalement long (un
  `out` manqué ?), pause anormalement longue (discussion d'arbitres, ou un point
  raté ?), frontière proche de son seuil ;
- `game_<id>_curves.npz` — les trois courbes de probabilité le long du temps,
  pour affichage sous le lecteur.

## Métriques

`evaluate` décode des games entières et donne deux lectures :

- **frontières** : précision, rappel et écart médian par canal, à une tolérance
  paramétrable (±0.5 s par défaut, ce que valent les labels) ;
- **coût de revue** : nombre de points manqués et de segments en trop par game —
  le chiffre qui dit si l'outil fait gagner du temps.
