//import {BaseHalModel} from './base.model';

export interface Link {
  href: string;
  templated?: boolean;
  type?: string;
  deprecation?: string;
  name?: string;
  profile?: string;
  title?: string;
  hreflang?: string;
}

export interface HalLinks {
  self: Link;

  [key: string]: Link | undefined;
}

export interface Curies {
  curies?: Link[];
}

type DefaultHalLinks = HalLinks & Curies;

export interface HalEmbedded {
  [key: string]: Partial<BaseHalModel>;
}

export interface BaseHalModel {
  pk: number;
  _links?: HalLinks & Curies;
  _embedded?: HalEmbedded;
}

export interface Team extends BaseHalModel {
  name: string;
  short_name: string;
  image: string;
  slug: string;
  _links?: HalLinks & Curies;
}

export interface TournamentLinks extends HalLinks {
  self: Link;
  games?: Link;
  sync_videos?: Link;
  youtube_update?: Link;
  generate_games?: Link;
  create_game?: Link;
  rendered?: Link;
  source_files?: Link;
  archive?: Link;
  archive_all_games?: Link;
  video_metadatas?: Link;

  videos?: Link;
}

export interface Tournament extends BaseHalModel {
  pk: number;
  name: string;
  short_name?: string;
  date: string;
  place: string;
  JTR: string;
  tugeny_link: string;
  color: string;
  slug: string;
  is_archived?: boolean;
  _links?: TournamentLinks & Curies;
}

export interface VideoMetadataLinks extends HalLinks {
  self: Link;
  tournament?: Link;
  miniature_image?: Link;
  base_image?: Link;
  team1?: Link;
  team2?: Link;
  reset_url?: Link;
  upload_description?: Link;
  upload_miniature?: Link;
  set_yt_video?: Link;
}

export interface VideoMetadata extends BaseHalModel {
  pk: number;
  name: string;
  time_code: number;
  miniature_x_offset: number;
  miniature_y_offset: number;
  miniature_zoom: number;
  video_name: string;
  description: string;
  publication_date: string;
  _links?: VideoMetadataLinks & Curies;
  _embedded?: HalEmbedded;
}

export interface Yt_VideoLinks extends HalLinks {
  self: Link;
  linked_video?: Link;
}

export interface Yt_Video extends BaseHalModel {
  title: string;
  video_id: string;
  publication_date: string;
  privacy_status: string;
  _links?: Yt_VideoLinks & Curies;
  _embedded?: HalEmbedded;
}

export interface TmpImage extends BaseHalModel {
  pk: number;
  name: string;
  image: string;
  _links?: HalLinks;
  _embedded?: HalEmbedded;
}

export interface GameLinks extends HalLinks {
  self: Link;
  tournament?: Link;
  team1?: Link;
  team2?: Link;
  cuts?: Link;
  create_cut?: Link;
  generate_proxy?: Link;
  create_archive?: Link;
  ml_cut?: Link;
  video_proxy?: Link;
  archive_video?: Link;
}

export interface Game extends BaseHalModel {
  pk: number;
  name: string;
  files: string;
  /** Condition de victoire, en texte libre, affichee sur la carte d'ouverture. */
  condition?: string;
  sets_to_win?: number | null;
  /**
   * Score quand l'enregistrement commence, pour un match deja en cours : un
   * nombre par set pour chaque equipe, le dernier etant le set en cours.
   */
  start_score?: { team1: number[]; team2: number[] } | null;
  /** Numero de terrain, sur 2 chiffres. */
  field_number?: number;
  /** Numero de jour, sur 1 chiffre. */
  day_number?: number;
  /** Numero de la game dans la journee, sur 2 chiffres. */
  game_number?: number;
  /** Condition de victoire en code court, comme `1a10+2v` : elle nomme les rendus. */
  win_condition?: string;
  json_file: string;
  cuts: string[];
  /** Rendus de cuts en High h265 ou High AV1, presents sur le disque. */
  high_renders?: number;

  _links?: GameLinks;
  _embedded?: HalEmbedded;
}

export interface CutLinks extends HalLinks {
  self: Link;
  render?: Link;
  game?: Link;
  gen_from_file?: Link;
  gen_from_rendered?: Link;
  rendered_video?: Link;
  curves?: Link;
  redecode?: Link;
}

export interface Cut extends BaseHalModel {
  pk: number;
  name: string;
  type_cut: string;
  json_file: string;
  slug: string;
  valid?: boolean;
  /** Vrai quand le modele a laisse ses courbes de probabilite sur ce cut. */
  has_curves?: boolean;
  _links?: CutLinks;
  _embedded?: HalEmbedded;
}

/**
 * Les trois courbes de probabilite du modele, amincies pour l'affichage.
 *
 * `points` est ce qui est renvoye, `steps` ce que le fichier contient : le
 * serveur reduit `in` et `out` par leur maximum, `inside` par sa moyenne.
 */
export interface CutCurves {
  hop: number;
  duration: number;
  points: number;
  steps: number;
  /** Cadence de l'archive, pour passer des secondes aux frames du rush. */
  fps?: number | null;
  in: number[];
  out: number[];
  inside: number[];
  decode?: { threshold?: { in?: number; out?: number } };
  run?: string;
}

/**
 * Un endroit ou aller regarder : un point douteux, ou un candidat rejete.
 *
 * `at` est en secondes de l'archive, `kind` dit pourquoi (`in_incertain`,
 * `pause_longue`, `out_orphelin`...), `detail` le raconte en une ligne.
 */
export interface CutReviewItem {
  at: number;
  kind: string;
  detail: string;
}

/** Le bloc que le modele laisse dans le fichier de cut : sa provenance. */
export interface CutComment {
  generated_by?: string;
  model?: { run?: string; redecoded?: boolean; snapped?: boolean };
  fps?: number;
  decode?: { threshold?: { in?: number; out?: number } };
  stats?: { duration?: number; kept?: number; kept_ratio?: number };
  /** Ce que le modele a propose mais dont il n'est pas sur. */
  review?: CutReviewItem[];
  /** Ce qu'il a failli proposer, et pourquoi il ne l'a pas fait. */
  rejected?: CutReviewItem[];
  /**
   * Ce que le classifieur pense du camp gagnant de chaque point, sur les
   * memes segments que ceux proposes. Une suggestion, jamais un label : le
   * champ `point` d'un point n'est rempli que par un humain.
   */
  sides?: CutSideGuess[];
  curves_file?: string;
  curves_hop?: number;
}

/** Le camp devine pour un point, et la confiance du modele. */
export interface CutSideGuess {
  in: number;
  out: number;
  point: 'left' | 'right';
  confidence: number;
}

/** Reglages du decodage : ce qu'on tourne quand l'outil propose trop ou trop peu. */
export interface DecodeSettings {
  threshold_in: number;
  threshold_out: number;
  min_gap: number;
  snap: boolean;
}

/** Reponse de `cuts/{id}/redecode` : ce que donnerait ce reglage. */
export interface RedecodeResponse {
  applied: boolean;
  /** Faux quand l'enveloppe d'attaques manque : les debuts ne sont pas cales. */
  snapped: boolean;
  segments: number;
  points: { in: number; out: number; point?: string }[];
  stats: { kept: number; duration: number; kept_ratio: number };
  review: { at: number; kind: string; detail: string }[];
}

/** Reponse de `games/{id}/ml-cut` : le cut vide, et le job qui le remplit. */
export interface MlCutResponse {
  detail: string;
  cut: Cut;
  render_queue_item_id: number;
  status: string;
  run: string;
}

export type VideoQuality = 'low' | 'medium' | 'high' | 'archive';

/** Fichiers reellement rendus, indexes par qualite : toutes sont optionnelles. */
export type VideoFiles = Partial<Record<VideoQuality, VideoFile>>;

export interface VideoFile extends BaseHalModel {
  url: string;
  format: string;
  /** Frame rate reelle du fichier, null si non sondee. */
  fps: number | null;
}
export interface VideoLinks extends HalLinks {
  self: Link;
  game?: Link;
  cut?: Link;
}

export interface Video extends BaseHalModel {
  pk: number;
  duration: number;
  owner_type: string;
  files: VideoFiles;
  _links?: VideoLinks;
  _embedded?: HalEmbedded;
}

export interface RenderQueueItemLinks extends HalLinks {
  self: Link;
  run?: Link;
  reset?: Link;
}

export interface RenderQueueItem extends BaseHalModel {
  pk: number;
  cut?: number | null;
  cut_name?: string;
  game?: number | null;
  game_name?: string;
  preset: string;
  metadata: string;
  status: string;
  command?: string;
  error?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  _links?: RenderQueueItemLinks & Curies;
}

export interface OtherModel extends BaseHalModel {
  [key: string]: string | number | boolean | HalLinks | HalEmbedded | undefined;
}
