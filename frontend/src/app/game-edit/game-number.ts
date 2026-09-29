/** Les bornes de chaque partie du numero, celles du modele cote serveur. */
export const GAME_NUMBER_MAX = { field: 99, day: 9, game: 99 } as const;

/**
 * Lit une partie du numero telle qu'on la tape. Ce qui n'est pas un entier
 * compte pour zero, et la valeur est ramenee dans ses bornes.
 */
export function numberPart(value: unknown, max: number): number {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) return 0;
  return Math.min(n, max);
}

/**
 * Le numero d'une game, TTJGG : le terrain et la game sur deux chiffres, le
 * jour sur un. C'est ce qui ouvre le nom de ses rendus.
 */
export function gameNumber(
  field: unknown,
  day: unknown,
  game: unknown,
): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    pad(numberPart(field, GAME_NUMBER_MAX.field)) +
    String(numberPart(day, GAME_NUMBER_MAX.day)) +
    pad(numberPart(game, GAME_NUMBER_MAX.game))
  );
}
