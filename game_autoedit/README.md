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
make autoedit-dashboard          # (re)démarre en tâche de fond sur le port 8501
make autoedit-dashboard-status   # lancé ou pas
make autoedit-dashboard-logs     # suivre le journal
make autoedit-dashboard-stop
make autoedit-dashboard-fg       # au premier plan, pour déboguer
```

`autoedit-dashboard` **arrête toujours le serveur en cours avant de démarrer**.
C'est la bonne réaction à un écran qui montre un état périmé : Streamlit garde
ses caches d'une exécution à l'autre, et Django ne sait pas recharger un modèle
une fois enregistré.

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

## Images

Le son ne dit pas tout : un coup de sifflet peut venir du terrain d'à côté, et
un point qui commence se voit — deux équipes alignées sur leurs lignes de fond,
puis la course au centre. Un second encodeur gelé, **DINOv2** (ViT-B/14), lit
donc aussi les images.

```bash
# une fois : 5 images/s, ~1 min 30 par heure de game sur la 2080
python -m game_autoedit build-embeddings --encoder dinov2 --batch-size 64

# une tête sur le son et l'image
python -m game_autoedit train --name fusion --encoder ast_ms+dinov2
```

- **Source** : le proxy (`low`, sinon `medium`, sinon `low_av1`), l'archive à
  défaut. Même timeline que l'archive, décodé dix fois plus vite (l'AV1 de
  l'archive n'a pas de décodeur matériel sur Turing), et l'encodeur regarde les
  images en 448×252 de toute façon : la définition de la source ne change rien
  au modèle.
- **Plongement** : par image, le token CLS et la moyenne des patches de trois
  bandes verticales — gauche, centre, droite — soit 4 × 768 = 3072 dimensions.
  Le terrain court à travers l'image : les bandes disent de quel côté est le
  jeu.
- **Fusion** : `--encoder a+b` lit les caches côte à côte sur la grille du
  premier (le son, ~10 Hz) ; chaque pas prend l'image la plus proche. Rien
  n'est dupliqué sur disque.
- **`--video-dropout`** (0.2) masque les images d'une fenêtre entière, pour que
  le son garde voix au chapitre.

### Camp qui marque

`train-side` ajuste un **classifieur séparé** qui répond, pour un point déjà
découpé, quel camp de l'image l'a gagné.

```bash
python -m game_autoedit train-side --run fusion
python -m game_autoedit evaluate --run fusion --part val   # donne le taux de camps justes
```

- **Ce qu'il lit** : un seul vecteur par point, dans les dix secondes qui
  précèdent la fin,
  tenu à l'écart des points voisins *et* des secondes qui suivent le point
  précédent, où se lit le gagnant du précédent. Le début du point ne borne
  rien : 2 points étiquetés sur 303 durent moins de 8 s, et les borner ne
  changeait rien. Une sonde linéaire lit le camp à 0.73 sur cette
  fenêtre et à **0.57 — le hasard — moyennée sur tout le point** : ce qui
  désigne le gagnant, c'est la pierre posée et la réaction des équipes, pas le
  jeu. Et tout se joue **avant** la coupe : une fenêtre à cheval sur la fin
  tombe à 0.85, une qui court vingt secondes après à 0.76. La pierre est posée
  un temps avant que le monteur ne coupe ; après, on filme des joueurs qui
  rentrent.
- **Pondération** (`--profile`, `--profile-rate`) : par défaut une **loi de
  Poisson de moyenne 2.3 s** avant la fin, nulle à la coupe et après. Elle n'a
  pas été devinée : le profil a été appris avec le classifieur, sur plusieurs
  familles classiques.

  | Famille apprise | Camps justes | Où elle a choisi de regarder |
  |---|---|---|
  | Poisson | 0.898 ± 0.001 | centre −2.5 s |
  | Profil libre (137 poids) | 0.894 ± 0.003 | centre −3.0 s |
  | Fenêtre plate fixe | 0.892 ± 0.007 | centre −3.0 s |
  | Gaussienne | 0.892 ± 0.006 | centre −2.9 s |
  | Chi-2 | 0.885 ± 0.007 | centre −2.6 s |
  | Log-normale | 0.885 ± 0.013 | centre −2.8 s |
  | Gamma | 0.884 ± 0.013 | centre −2.8 s |
  | **Gamma retournée vers l'après** | **0.795 ± 0.010** | centre +3.8 s |

  Toutes convergent entre 2.5 et 3 s avant la coupe, y compris le profil libre
  qui n'a aucune contrainte de forme ; aucune ne bat les autres au-delà de la
  dispersion entre tirages. Seule l'inversion tranche, et elle s'effondre : il
  n'y a rien à lire après la coupe. Le profil reste donc un paramètre, à
  réapprendre quand il y aura plus de games étiquetées.
- **Le profil voyage avec le cut**, dans `comment.model.side_profile`, et avec
  le classifieur dans `side.pt` : un re-décodage lit la courbe exactement comme
  elle a été écrite.
- **Ce vecteur est une asymétrie**, pas une description : la bande gauche moins
  la bande droite, moins la moyenne de la game. Sur les plongements bruts le
  classifieur tombait à 0.74 et répondait « gauche » dix-huit fois de suite, à
  1.00 de confiance, sur une game jamais vue : avec 4608 dimensions pour 200
  points, il reconnaissait le match. La différence des bandes annule le lieu,
  la caméra et les couleurs des équipes ; retrancher la moyenne de la game
  annule ce que ce match a de constant.
- **`--no-mirror`** retire l'augmentation par miroir, active par défaut. Sur
  cette représentation un miroir est un simple changement de signe, donc exact,
  et il vaut 0.84 contre 0.82 en validation croisée.
- **Où il vit** : `side.pt`, à côté du `best.pt` du run. `evaluate`, `predict`
  et `propose` s'en servent dès qu'il est là, et l'ignorent sinon.
- **Une courbe, pas une réponse par point** : le classifieur est linéaire, donc
  son score au pas de temps est stocké dans le `.npz` avec les trois autres
  canaux. Re-décoder avec d'autres seuils recalcule le camp de chaque nouveau
  segment sans modèle ni GPU, au lieu de traîner des réponses périmées.
- **Sortie** : le camp deviné et sa confiance vont dans `comment.sides` du cut
  proposé, **pas** dans le champ `point` des points. Un camp dans `point` est
  ce qui distingue une proposition relue d'une proposition brute (voir
  ci-dessous) ; le modèle n'y écrit jamais. L'éditeur les montre à droite du
  sélecteur, en lecture seule et grisés.

### Ce que valent les camps

| Mesure, en validation | |
|---|---|
| Camps justes | **0.89** (79 points, 6 games, 2 tournois) |
| Constante « toujours à gauche » | 0.70 |
| Points minoritaires de leur game | 0.89 |
| Validation croisée par game | 0.90 |
| Confiance médiane | 0.92 |
| Tolérance à une fin mal placée | ±2 s sans perte, -0.17 à ±4 s |

Les labels : 247 points d'entraînement sur 18 games, 79 de validation sur 6, 43
de test sur 4. Le choix de la pondération, lui, s'est joué à trois points sur
64 entre Poisson et une fenêtre plate — du bruit à cette taille ; c'est la
validation croisée par game qui a tranché, de justesse.

La ligne des points minoritaires est celle qui compte. Les matchs se jouent en
un set (`1a8`, `1a10`), sans changement de côté : une équipe qui domine marque
tous ses points du même côté de l'image, et 70 % des points de validation
tombent à gauche. Un modèle qui répondrait toujours « gauche » afficherait donc
0.70. Le classifieur est aussi bon sur les points qui vont *contre* la tendance
de leur propre match que sur les autres (0.89 des deux côtés) : il lit bien
l'action, pas le score du match.

Une part du score reste néanmoins commune à toute une game, et c'est légitime :
elle suit le vrai déséquilibre du match (corrélation 0.94 sur les games
étiquetées, 0.62 sur les cinq de validation). Un 8-0 *est* à sens unique. Ce
qu'il fallait chasser, c'est la part qui venait du décor.

**Pourquoi un modèle à part.** Le camp a d'abord été un quatrième canal de la
tête, appris avec les frontières. Il est resté au hasard, et pour une raison
structurelle : 15 games sur 200 portent un camp, donc un lot de 8 fenêtres n'en
contient presque jamais deux. Le camp apprenait un exemple à la fois et sortait
une constante qui basculait à chaque epoch (0.30 puis 0.70, soit exactement la
proportion de « gauche » en validation). Lui donner sa propre branche n'y a rien
changé. À part, il s'ajuste en quelques secondes sur quelques centaines de
points, et il ne peut plus déranger les frontières.

### Propositions relues

Un cut de type `ML` sert à l'entraînement dès qu'un de ses points porte un camp
: le modèle n'en écrit jamais, c'est donc la trace d'un passage humain, qui a
aussi corrigé les frontières. Une proposition relue sans remplir aucun camp
reste écartée.

Une telle proposition passe aussi **devant un cut `VID`** du même game, qui est
reconstruit par alignement audio. Sans cette règle, cinq games d'un tournoi
étaient lues depuis leur jumeau `VID` et leurs 66 camps ignorés — un cinquième
des labels, et le seul tournoi hors WCC à en porter.

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
  pour affichage sous le lecteur ;
- un bloc `comment.sides` — pour chaque point, le camp deviné et sa confiance,
  quand le run porte un classifieur de camp.

## Métriques

`evaluate` décode des games entières et donne deux lectures :

- **frontières** : précision, rappel et écart médian par canal, à une tolérance
  paramétrable (±0.5 s par défaut, ce que valent les labels) ;
- **coût de revue** : nombre de points manqués et de segments en trop par game —
  le chiffre qui dit si l'outil fait gagner du temps ;
- **camp** : part des points bien attribués, sur les points du montage humain
  qui portent un camp, quand le run en a un.

Mesuré en validation (41 games, tolérance ±2 s), sur le catalogue complet :

| | son seul | image seule | son + image |
|---|---|---|---|
| F1 `in` | 0.72 | 0.85 | **0.87** |
| F1 `out` | 0.50 | 0.68 | **0.70** |
| IoU | 0.61 | 0.72 | **0.78** |
| points manqués par game | 2.5 | 2.4 | **1.3** |
| segments en trop par game | 2.2 | 0.7 | **1.1** |

L'image seule bat déjà le son seul. Les deux ensemble font mieux que chacune.
