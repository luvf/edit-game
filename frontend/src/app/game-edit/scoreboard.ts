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

/**
 * Le score quand l'enregistrement commence, pour un match deja en cours.
 *
 * Un nombre par set pour chaque equipe, du plus ancien au plus recent, les
 * deux listes de meme longueur : tous sauf le dernier sont des sets finis, le
 * dernier est le set en cours. C'est ce qui remplace les points de quelques
 * frames poses pour rattraper le score.
 */
export type StartScore = {
  team1: number[];
  team2: number[];
};

/**
 * Lit les scores d'une equipe tapes comme `10-3` : le tiret separe les sets.
 * Ce qui n'est pas un entier positif compte pour zero.
 */
export function parseSetScores(text: string): number[] {
  if (!text.trim()) return [];
  return text.split(/[-–]/).map((piece) => {
    const value = Number.parseInt(piece.trim(), 10);
    return Number.isFinite(value) && value > 0 ? value : 0;
  });
}

/**
 * Apparie les scores des deux equipes, en completant la plus courte par des
 * zeros a droite. `undefined` quand aucune n'a de score.
 */
export function pairStartScore(
  team1: readonly number[],
  team2: readonly number[],
): StartScore | undefined {
  const length = Math.max(team1.length, team2.length);
  if (!length) return undefined;
  const pad = (scores: readonly number[]) => [
    ...scores,
    ...Array<number>(length - scores.length).fill(0),
  ];
  return { team1: pad(team1), team2: pad(team2) };
}

/**
 * Relit les scores d'une equipe tels que le fichier les porte : une liste, ou
 * du texte ecrit a la main.
 */
export function readSetScores(value: unknown): number[] {
  if (typeof value === 'string') return parseSetScores(value);
  if (!Array.isArray(value)) return [];
  return value.map((item) => parseSetScores(String(item))[0] ?? 0);
}

/** Ecrit les scores d'une equipe comme on les tape : `10-3`. */
export function formatSetScores(scores: readonly number[] | undefined): string {
  return (scores ?? []).join('-');
}

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

/** Les sets finis et le set en cours au depart, 0-0 sans score de depart. */
function opening(start?: StartScore): {
  team1: number;
  team2: number;
  sets: SetScore[];
} {
  const count = Math.min(start?.team1.length ?? 0, start?.team2.length ?? 0);
  if (!start || !count) return { team1: 0, team2: 0, sets: [] };
  const sets = start.team1
    .slice(0, count - 1)
    .map((team1, index) => ({ team1, team2: start.team2[index] }));
  return { team1: start.team1[count - 1], team2: start.team2[count - 1], sets };
}

function startState(start?: StartScore): BoardState {
  const { team1, team2, sets } = opening(start);
  return {
    left: 'team1',
    right: 'team2',
    leftScore: team1,
    rightScore: team2,
    finishedSets: sets,
    setNumber: sets.length + 1,
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
 * @param start le score quand l'enregistrement commence, 0-0 sans lui
 * @returns un etat par point
 */
export function buildStates(
  points: readonly ScoringPoint[],
  events: readonly ScoringEvent[],
  start?: StartScore,
): BoardState[] {
  const ordered = [...events].sort((a, b) => a.tc - b.tc);
  const states: BoardState[] = [];

  // L'equipe 1 commence a gauche, toujours : c'est l'ordre team1/team2 du
  // match qui le porte, et le bouton d'inversion le change.
  let left: Side = 'team1';
  const initial = opening(start);
  let team1 = initial.team1;
  let team2 = initial.team2;
  const sets = initial.sets;
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
 * Les evenements qui comptent pour le score, tels que le tableau les lit.
 *
 * Un `Warning` n'en est pas : il s'affiche, il ne deplace ni les cotes ni les
 * sets. Le filtrer ici plutot qu'a chaque appelant evite qu'un oubli fasse
 * basculer les cotes sur un avertissement.
 */
export function scoringEvents(
  events: readonly { type: 'SideSwitch' | 'SetEnd' | 'Warning'; tc: number }[],
): ScoringEvent[] {
  return events
    .filter((event) => event.type !== 'Warning')
    .map((event) => ({
      type: event.type as ScoringEvent['type'],
      tc: event.tc,
    }));
}

/**
 * L'equipe qui marque a chaque point, `null` quand le point ne marque pas.
 *
 * `left` et `right` sont des cotes de terrain, pas des equipes : apres un
 * `SideSwitch`, un point `left` revient a l'autre equipe. C'est cette liste
 * qu'il faut lire pour colorer un point par son equipe, et elle est derivee de
 * `buildStates` pour que la regle des cotes ne soit ecrite qu'une fois.
 *
 * @param points les points du cut, dans l'ordre du montage
 * @param events les changements de cote et fins de set, en frames du rush
 * @returns une entree par point, dans le meme ordre
 */
export function scorers(
  points: readonly ScoringPoint[],
  events: readonly ScoringEvent[],
): (Side | null)[] {
  const states = buildStates(points, events);
  return points.map((point, index) => {
    const state = states[index];
    if (point.point === 'left') return state.left;
    if (point.point === 'right') return state.right;
    return null;
  });
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
  start?: StartScore,
): BoardState {
  const last: ScoringPoint = { in: Number.POSITIVE_INFINITY };
  const states = buildStates([...points, last], events, start);
  return states[states.length - 1];
}

/**
 * L'etat du tableau a une frame du rush, telle que le rendu l'affichera.
 *
 * Pendant un point, c'est le tableau de ce point. Entre deux points, le
 * montage saute l'intervalle : on rend alors le tableau du point suivant,
 * c'est-a-dire le score avec lequel la video repartira. Apres le dernier
 * point, c'est le score final.
 *
 * @param points les points du cut, ordonnes par `in`
 * @param events les changements de cote et fins de set
 * @param frame la frame du rush ou l'on regarde
 * @param start le score quand l'enregistrement commence
 * @returns l'etat du tableau, ou l'etat de depart si le cut n'a pas de point
 */
export function stateAtFrame(
  points: readonly (ScoringPoint & { out: number })[],
  events: readonly ScoringEvent[],
  frame: number,
  start?: StartScore,
): BoardState {
  if (!points.length) return startState(start);

  const states = buildStates(points, events, start);

  let index = -1;
  points.forEach((point, rank) => {
    if (point.in <= frame) index = rank;
  });

  if (index < 0) return states[0];
  if (frame <= points[index].out) return states[index];
  return states[index + 1] ?? closingState(points, events, start);
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
