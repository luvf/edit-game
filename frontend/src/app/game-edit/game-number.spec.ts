import { gameNumber, numberPart } from './game-number';

describe('gameNumber', () => {
  it('pads the terrain and the game to two digits', () => {
    expect(gameNumber(8, 2, 5)).toBe('08205');
  });

  it('needs no padding for a two-digit terrain', () => {
    expect(gameNumber(12, 2, 7)).toBe('12207');
  });

  it('reads empty or invalid parts as zero', () => {
    expect(gameNumber(null, '', 'abc')).toBe('00000');
  });

  it('accepts parts typed as text', () => {
    expect(gameNumber('10', '2', '8')).toBe('10208');
  });
});

describe('numberPart', () => {
  it('keeps a value within its bound', () => {
    expect(numberPart(12, 9)).toBe(9);
  });

  it('reads a negative or fractional value as zero', () => {
    expect(numberPart(-3, 99)).toBe(0);
    expect(numberPart(2.5, 99)).toBe(0);
  });
});
