import { suggestionForPoint } from './cut-detail';
import { CutSideGuess } from '../../core/models/models';

/** Une suggestion du modele, telle qu'elle arrive dans `comment.sides`. */
function guess(
  inFrame: number,
  outFrame: number,
  point: 'left' | 'right',
): CutSideGuess {
  return { in: inFrame, out: outFrame, point, confidence: 0.9 };
}

describe('suggestionForPoint', () => {
  const sides = [guess(100, 200, 'left'), guess(400, 600, 'right')];

  it('rend la suggestion du point qu elle recouvre', () => {
    expect(suggestionForPoint(sides, { in: 400, out: 600 })?.point).toBe(
      'right',
    );
  });

  it('suit un point dont on a deplace les frontieres', () => {
    // Le monteur a rallonge le debut et raccourci la fin : c'est toujours le
    // meme point, et l'avis du modele doit le suivre.
    expect(suggestionForPoint(sides, { in: 380, out: 540 })?.point).toBe(
      'right',
    );
  });

  it('prend la suggestion qui recouvre le plus', () => {
    expect(suggestionForPoint(sides, { in: 150, out: 450 })?.point).toBe(
      'left',
    );
  });

  it('ne dit rien sur un point ajoute ailleurs', () => {
    expect(suggestionForPoint(sides, { in: 800, out: 900 })).toBeNull();
  });

  it('ne dit rien quand deux points se touchent sans se recouvrir', () => {
    expect(suggestionForPoint(sides, { in: 200, out: 400 })).toBeNull();
  });

  it('ne dit rien sans suggestions', () => {
    expect(suggestionForPoint(undefined, { in: 100, out: 200 })).toBeNull();
  });
});
