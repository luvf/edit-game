/**
 * Ce que dit le tableau de score, a un point donne du montage.
 *
 * C'est la meme regle que `jugger_video_manipulation/scoreboard.py`, tenue
 * deux fois : ici pour l'afficher pendant que tu montes, la-bas pour le
 * dessiner dans la video. Les deux jeux de tests couvrent les memes cas, ce
 * qui est la seule chose qui les empeche de diverger en silence.
 *
 * Aucun score n'est stocke. Il decoule des points et des evenements, donc un
 * fichier de cut ne peut pas contenir un score qui contredit ses points.
 */

/** Un point du cut, en frames du rush. */
export type ScoringPoint = {
  in: number;
  point?: 'left' | 'right' | 'nopoint';
};

/** Un evenement qui change la lecture du score, sans rien dessiner. */
export type ScoringEvent = {
  type: 'SideSwitch' | 'SetEnd';
  tc: number;
};

/** Un set termine, vu comme les totaux des deux equipes. */
export type SetScore = {
  team1: number;
  team2: number;
};

/** Le cote d'une equipe, qui change a chaque `SideSwitch`. */
export type Side = 'team1' | 'team2';

/** L'etat du tableau a un instant du montage. */
export type BoardState = {
  /** L'equipe qui se trouve a gauche a cet instant. */
  left: Side;
  right: Side;
  leftScore: number;
  rightScore: number;
  finishedSets: SetScore[];
  setNumber: number;
};

function startState(): BoardState {
  return {
    left: 'team1',
    right: 'team2',
    leftScore: 0,
    rightScore: 0,
    finishedSets: [],
    setNumber: 1,
  };
}

/**
 * Etat du tableau devant chaque point, dans l'ordre de la liste.
 *
 * L'element `i` est ce qu'affiche le tableau *pendant* le point `i` : le score
 * avec lequel l'action commence, comme un vrai tableau pendant le jeu. Il y a
 * donc exactement un etat par point : le score du dernier point n'y figure
 * pas, `closingState` est la pour ca.
 *
 * Une seule difference avec le Python, voulue : la-bas les etats identiques
 * consecutifs sont fusionnes, pour ne pas dessiner deux fois la meme image.
 * Ici il en faut un par ligne, puisqu'on affiche le score en face de chaque
 * point. Le contenu des etats, lui, est le meme des deux cotes.
 *
 * @param points les points du cut, dans l'ordre du montage
 * @param events les changements de cote et fins de set, en frames du rush
 * @returns un etat par point
 */
export function buildStates(
  points: readonly ScoringPoint[],
  events: readonly ScoringEvent[],
): BoardState[] {
  const ordered = [...events].sort((a, b) => a.tc - b.tc);
  const states: BoardState[] = [];

  // L'equipe 1 commence a gauche, toujours : c'est l'ordre team1/team2 du
  // match qui le porte, et le bouton d'inversion le change.
  let left: Side = 'team1';
  let team1 = 0;
  let team2 = 0;
  const sets: SetScore[] = [];
  let next = 0;

  const snapshot = (): BoardState => ({
    left,
    right: left === 'team1' ? 'team2' : 'team1',
    leftScore: left === 'team1' ? team1 : team2,
    rightScore: left === 'team1' ? team2 : team1,
    finishedSets: sets.map((set) => ({ ...set })),
    setNumber: sets.length + 1,
  });

  const applyUntil = (frame: number): void => {
    while (next < ordered.length && ordered[next].tc <= frame) {
      if (ordered[next].type === 'SideSwitch') {
        left = left === 'team1' ? 'team2' : 'team1';
      } else {
        sets.push({ team1, team2 });
        team1 = 0;
        team2 = 0;
      }
      next += 1;
    }
  };

  for (const point of points) {
    applyUntil(point.in);
    states.push(snapshot());

    if (point.point === 'left' || point.point === 'right') {
      const right: Side = left === 'team1' ? 'team2' : 'team1';
      const scorer: Side = point.point === 'left' ? left : right;
      if (scorer === 'team1') {
        team1 += 1;
      } else {
        team2 += 1;
      }
    }
  }

  return states;
}

/**
 * Le score une fois tous les points comptes.
 *
 * `buildStates` s'arrete au dernier point sans compter son resultat, parce
 * qu'un tableau affiche le score avec lequel l'action commence. Le score final
 * n'apparait donc nulle part dans cette liste : c'est ce que rend cette
 * fonction. Cote Python, c'est l'etat que `hold_final` ajoute.
 */
export function closingState(
  points: readonly ScoringPoint[],
  events: readonly ScoringEvent[],
): BoardState {
  const last: ScoringPoint = { in: Number.POSITIVE_INFINITY };
  const states = buildStates([...points, last], events);
  return states[states.length - 1];
}

/** Etat du tableau devant le point `index`, borne aux etats disponibles. */
export function stateAt(
  states: readonly BoardState[],
  index: number,
): BoardState {
  if (!states.length) return startState();
  const bounded = Math.min(Math.max(index, 0), states.length - 1);
  return states[bounded];
}
