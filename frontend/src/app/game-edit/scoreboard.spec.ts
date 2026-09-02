import { buildStates, closingState, stateAt } from './scoreboard';

/**
 * Ces cas sont ceux de `scratchpad`/`test_scoreboard.py` cote Python : la
 * regle est tenue deux fois, et seuls des tests sur les memes cas
 * l'empechent de diverger d'un cote sans qu'on le voie.
 *
 * Une difference de forme est voulue : le Python fusionne les etats
 * identiques consecutifs pour ne pas dessiner deux fois la meme image, ici
 * on en garde un par ligne. Le contenu, lui, doit concorder.
 */

const point = (frame: number, scored?: 'left' | 'right' | 'nopoint') => ({
  in: frame,
  point: scored,
});

describe('buildStates', () => {
  it('rend un etat par point', () => {
    expect(buildStates([point(0), point(600), point(1200)], []).length).toBe(3);
  });

  it('donne le score du debut du point, pas de sa fin', () => {
    const states = buildStates([point(0, 'left'), point(600)], []);

    expect(states[0].leftScore).toBe(0);
    expect(states[1].leftScore).toBe(1);
  });

  it("l'equipe 1 commence a gauche", () => {
    expect(buildStates([point(0)], [])[0].left).toBe('team1');
  });

  it('sans point, aucun etat', () => {
    expect(buildStates([], []).length).toBe(0);
  });
});

describe('closingState', () => {
  it("compte le dernier point, que buildStates n'affiche pas", () => {
    const points = [point(0, 'left')];

    expect(buildStates(points, [])[0].leftScore).toBe(0);
    expect(closingState(points, []).leftScore).toBe(1);
  });

  it("attribue un point a l'equipe qui se trouve de ce cote", () => {
    expect(closingState([point(0, 'left')], []).left).toBe('team1');
  });

  it('un changement de cote deplace les equipes, pas les scores', () => {
    const last = closingState(
      [point(0, 'left'), point(600)],
      [{ type: 'SideSwitch', tc: 300 }],
    );

    expect(last.left).toBe('team2');
    // team1 a marque, et se trouve maintenant a droite.
    expect(last.leftScore).toBe(0);
    expect(last.rightScore).toBe(1);
  });

  it('deux changements ramenent au depart', () => {
    const last = closingState(
      [point(0), point(600)],
      [
        { type: 'SideSwitch', tc: 100 },
        { type: 'SideSwitch', tc: 200 },
      ],
    );

    expect(last.left).toBe('team1');
  });

  it('une fin de set archive le score et remet a zero', () => {
    const last = closingState(
      [point(0, 'left'), point(60, 'left'), point(600)],
      [{ type: 'SetEnd', tc: 300 }],
    );

    expect(last.finishedSets).toEqual([{ team1: 2, team2: 0 }]);
    expect(last.leftScore).toBe(0);
    expect(last.setNumber).toBe(2);
  });

  it('applique les evenements dans l ordre des timecodes', () => {
    const last = closingState(
      [point(0, 'left'), point(600, 'left')],
      [
        { type: 'SetEnd', tc: 300 },
        { type: 'SideSwitch', tc: 300 },
      ],
    );

    expect(last.finishedSets).toEqual([{ team1: 1, team2: 0 }]);
    // apres le switch team2 est passee a gauche : le second point marque
    // `left` lui revient, pas a team1.
    expect(last.left).toBe('team2');
    expect(last.leftScore).toBe(1);
  });

  it('un point sans cote ne change rien', () => {
    expect(closingState([point(0, 'nopoint'), point(600)], []).leftScore).toBe(
      0,
    );
  });
});

describe('stateAt', () => {
  it("borne l'index aux deux bouts", () => {
    const states = buildStates([point(0, 'left'), point(600)], []);

    expect(stateAt(states, 99).leftScore).toBe(1);
    expect(stateAt(states, -5).leftScore).toBe(0);
  });

  it('sans etat, rend le depart', () => {
    expect(stateAt([], 0).left).toBe('team1');
    expect(stateAt([], 0).leftScore).toBe(0);
  });
});
