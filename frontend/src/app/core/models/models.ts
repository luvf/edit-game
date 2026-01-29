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
  curies?: Link[]
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
  generate_games?:Link;

  videos?: Link;
}

export interface Tournament extends BaseHalModel {
  pk: number;
  name: string;
  date: string;
  place: string;
  JTR: string;
  tugeny_link: string;
  color: string;
  slug: string;
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
  _embedded?: HalEmbedded
}


export interface Yt_VideoLinks extends HalLinks {
  self: Link;
  video_metadata?: Link;
}

export interface Yt_Video extends BaseHalModel {
  title: string;
  video_id: string;
  publication_date: string;
  privacy_status: string;
  _links?: Yt_VideoLinks & Curies;
  _embedded?: HalEmbedded

}


export interface TmpImage extends BaseHalModel {
  pk: number;
  name: string;
  image: string;
  _links?: HalLinks;
  _embedded?: HalEmbedded

}

export interface GameLinks extends HalLinks {
  self: Link;
  tournament?: Link;
  team1?:Link;
  team2?:Link;
  cuts?:Link;
  create_cut?: Link;
  generate_proxy?:Link
}

export interface Game extends BaseHalModel {
  pk: number;
  name: string;
  files: string;
  rendered: string;
  json_file: string;
  source_proxy:string;
  cuts: string[];

  _links?: GameLinks;
  _embedded?: HalEmbedded

}

export interface CutLinks extends HalLinks {
  self: Link;
  render?:Link;
  game?: Link;

}

export interface Cut extends BaseHalModel {
  pk: number;
  name: string;
  type_cut: string;
  json_file: string;

  slug: string;
  valid?: boolean;
  _links?: CutLinks
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
  status: string;
  output_filename?: string;
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
