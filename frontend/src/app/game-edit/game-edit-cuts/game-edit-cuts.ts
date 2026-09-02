import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  signal,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import {
  CutsService,
  GamesService,
} from '../../core/services/misc-hateoas-models.service';
import { TournamentService } from '../../core/services/tournament.service';
import {
  Cut,
  Game,
  Tournament,
  Video,
  VideoFile,
  VideoFiles,
  VideoQuality,
} from '../../core/models/models';
import { CutDetailComponent } from '../cut-detail/cut-detail';
import { CutTimelineComponent } from '../cut-timeline/cut-timeline';
import { VideoPlayer } from '../video-player/video-player';
import { GameEditCutsStateService } from './game-edit-cuts-state';

type CutTemplate = {
  code: string;
  label: string;
};

/**
 * Largeur du panneau lateral en dessous de laquelle les points et les overlays
 * d'un cut passent en onglets plutot que cote a cote.
 */
const COMPACT_PANEL_WIDTH = 1000;

/**
 * Fichier a exposer pour l'archive d'un match.
 *
 * Les archives recentes sont stockees en qualite `archive`, les plus
 * anciennes sous le preset qui les a produites (`high`). Une seule entree
 * suffit : c'est le meme master.
 */
function pickArchiveFile(files: VideoFiles): VideoFile | null {
  const entries = Object.entries(files) as [
    VideoQuality,
    VideoFile | undefined,
  ][];
  const preferred = entries.find(([quality]) => quality === 'archive');
  return (preferred ?? entries[0])?.[1] ?? null;
}

@Component({
  selector: 'app-game-edit-cuts',
  standalone: true,
  providers: [GameEditCutsStateService],

  imports: [
    CommonModule,
    FormsModule,
    MatTabsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    CutDetailComponent,
    CutTimelineComponent,
    VideoPlayer,
  ],
  templateUrl: './game-edit-cuts.html',
  styleUrl: './game-edit-cuts.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GameEditCutsComponent
  implements AfterViewInit, OnChanges, OnDestroy, OnInit
{
  @Input() game?: Game | null = null;
  cuts = signal<Cut[]>([]);
  cutsVideos = signal<Record<string, Video>>({});
  proxyGameVideo = signal<Video | null>(null);
  /** Archive du match, seulement si elle est liee et qu'un fichier existe. */
  archiveGameVideo = signal<Video | null>(null);
  /**
   * Source du lecteur de rush : les fichiers du proxy et ceux de l'archive
   * reunis, pour que l'archive soit un choix de plus dans le menu qualite.
   */
  rushVideo = computed<Video | null>(() => {
    const proxy = this.proxyGameVideo();
    const archive = this.archiveGameVideo();
    // L'archive est toujours republiee sous la cle `archive` : une archive
    // ancienne est stockee en `high` et ecraserait sinon la qualite du proxy
    // qui porte ce nom.
    const archiveFile = archive ? pickArchiveFile(archive.files) : null;
    const archiveFiles: VideoFiles | null = archiveFile
      ? { archive: archiveFile }
      : null;
    if (!proxy) {
      return archive && archiveFiles
        ? { ...archive, files: archiveFiles }
        : archive;
    }
    if (!archiveFiles) return proxy;
    return {
      ...proxy,
      files: { ...proxy.files, ...archiveFiles },
    };
  });
  cutTemplates = signal<CutTemplate[]>([]);
  newCutName = signal('');
  selectedCutType = signal<string | null>(null);
  loadedFile = signal<File | null>(null);
  renderedFiles = signal<string[]>([]);
  selectedRendered = signal<string | null>(null);
  selectedCutTabIndex = signal(0);

  /** Vrai quand le panneau lateral est trop etroit pour la vue en deux colonnes. */
  readonly compact = signal(false);

  @ViewChild('proxyVideo') proxyVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('rushPlayer') rushPlayer?: VideoPlayer;
  @ViewChild('sidePanel', { read: ElementRef })
  sidePanel?: ElementRef<HTMLElement>;
  protected readonly length = length;
  private state = inject(GameEditCutsStateService);
  rushFrame = this.state.rushFrame;
  renderedFrame = this.state.renderedFrame;
  rushFps = this.state.rushFps;
  rushDurationFrames = this.state.rushDurationFrames;
  activeCutPoints = this.state.activeCutPoints;
  hoveredPointIndex = this.state.hoveredPointIndex;
  activeCut = this.state.activeCut;
  private gameService = inject(GamesService);
  private cutService = inject(CutsService);
  private tournamentService = inject(TournamentService);
  private panelResize?: ResizeObserver;

  ngOnInit(): void {
    // Les cuts, rendered et la vidéo du match sont chargés par ngOnChanges,
    // qui se déclenche avant ngOnInit sur le premier binding de `game`.
    this.loadCutTemplates();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['game']) {
      this.loadCuts();
      this.loadRenderedFiles();
      this.loadGameVideo();
    }
  }

  ngAfterViewInit(): void {
    const panel = this.sidePanel?.nativeElement;
    if (!panel || typeof ResizeObserver === 'undefined') return;

    this.panelResize = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width === undefined) return;
      this.compact.set(width <= COMPACT_PANEL_WIDTH);
    });
    this.panelResize.observe(panel);
  }

  ngOnDestroy(): void {
    this.panelResize?.disconnect();
  }

  onGenerateCut(): void {
    if (!this.game) return;
    const selectedType = this.selectedCutType();
    const template = this.cutTemplates().find(
      (item) => item.code === selectedType,
    );
    if (!template) return;
    if (template.code === 'XML' && !this.loadedFile()) {
      console.error('Fichier XML manquant.');
      return;
    }
    if (template.code === 'OTIO' && !this.loadedFile()) {
      console.error('Fichier OTIO json manquant.');
      return;
    }
    if (template.code === 'VID' && !this.selectedRendered()) {
      console.error('Source rendered manquante.');
      return;
    }
    const name = this.newCutName().trim() || template.label;
    const payload = {
      name,
      slug: this.slugify(name),
      type_cut: template.code,
    };
    this.gameService.create_cut(this.game, payload).subscribe({
      next: (cut) => {
        this.cuts.set([...this.cuts(), cut]);
        this.newCutName.set('');
        const file = this.loadedFile();
        if (template.code === 'OTIO' && file) {
          this.cutService.gen_from_file(cut, file).subscribe({
            next: (updated) => {
              this.cuts.set(
                this.cuts().map((item) =>
                  item.pk === updated.pk ? updated : item,
                ),
              );
              this.loadedFile.set(null);
            },
            error: (e) =>
              console.error("Erreur lors de l'upload du json OTIO", e),
          });
        } else if (template.code === 'VID') {
          const filename = this.selectedRendered();
          if (!filename) return;
          this.cutService.gen_from_rendered(cut, { filename }).subscribe({
            next: (updated) => {
              this.cuts.set(
                this.cuts().map((item) =>
                  item.pk === updated.pk ? updated : item,
                ),
              );
              this.selectedRendered.set(null);
            },
            error: (e) =>
              console.error('Erreur lors du cut depuis rendered', e),
          });
        }
      },
      error: (e) => console.error('Erreur lors de la création du cut', e),
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement | null;
    const file = input?.files?.[0] ?? null;
    this.loadedFile.set(file);
  }

  onDeleteCut(cut: Cut, event?: MouseEvent): void {
    event?.stopPropagation();
    if (!this.game) return;
    const label = cut.name ?? cut.slug ?? 'ce cut';
    if (!confirm(`Supprimer ${label} ?`)) return;

    this.cutService.delete(cut).subscribe({
      next: () => {
        const nextCuts = this.cuts().filter((item) => item.pk !== cut.pk);
        this.cuts.set(nextCuts);

        if (this.selectedCutTabIndex() >= nextCuts.length) {
          this.selectedCutTabIndex.set(Math.max(0, nextCuts.length - 1));
        }
      },
      error: (e) => console.error('Erreur lors de la suppression du cut', e),
    });
  }

  onRenderCut(cut: Cut): void {
    this.cutService.render_cut(cut, { to_queue: false }).subscribe({
      next: () => {},
      error: (e) => console.error('Erreur lors du render du cut', e),
    });
  }

  onSeekRush(frame: number): void {
    this.rushFrame.set(frame);
    this.rushPlayer?.goToFrame(frame);
  }

  onSelectedCutTabChange(index: number): void {
    this.selectedCutTabIndex.set(index);
    // Le detail du nouvel onglet republiera ses points ; en attendant, mieux
    // vaut une timeline vide que les sections de l'onglet qu'on vient de quitter.
    this.activeCutPoints.set([]);
    this.hoveredPointIndex.set(null);
    this.activeCut.set(this.cuts()[index] ?? null);
  }

  private loadGameVideo(): void {
    const game = this.game;
    this.proxyGameVideo.set(null);
    this.archiveGameVideo.set(null);
    if (!game) return;

    this.gameService.proxy_video(game).subscribe({
      next: (video: Video) => {
        this.proxyGameVideo.set(video);
      },
      error: (error) => {
        console.error('Error loading game video:', error);
      },
    });
    this.loadArchiveVideo(game);
  }

  /**
   * Charge l'archive du match si elle est exposee par l'API.
   *
   * Un Video d'archive peut exister sans fichier rendu (la relation est creee
   * des la mise en file du rendu) : sans fichier, il n'y a rien a lire, donc
   * la source archive reste indisponible.
   */
  private loadArchiveVideo(game: Game): void {
    if (!game._links?.archive_video) return;
    this.gameService.archive_video(game).subscribe({
      next: (video: Video) => {
        if (!Object.keys(video?.files ?? {}).length) return;
        this.archiveGameVideo.set(video);
      },
      error: (e) =>
        console.error("Erreur lors du chargement de l'archive du match", e),
    });
  }

  private loadCuts(): void {
    if (!this.game) return;
    this.gameService.cuts(this.game).subscribe({
      next: (cuts: Cut[]) => {
        this.cuts.set(cuts);
        this.cuts().forEach((v) => this.loadCutVideo(v));
        const nextIndex =
          this.selectedCutTabIndex() >= cuts.length
            ? Math.max(0, cuts.length - 1)
            : this.selectedCutTabIndex();

        this.selectedCutTabIndex.set(nextIndex);
        this.activeCut.set(cuts[nextIndex] ?? null);
      },
      error: (e) => console.error('Erreur lors du chargement des cuts', e),
    });
  }
  private loadCutVideo(cut: Cut): void {
    this.cutService.rendered_video(cut).subscribe({
      next: (video: Video) => {
        const next1 = { ...this.cutsVideos() };
        next1[cut.pk] = video;
        this.cutsVideos.set(next1);
      },
      error: (e) => {
        console.error(`Erreur no rendered_video pour le cut ${cut.pk}`, e);
      },
    });
  }

  private loadCutTemplates(): void {
    this.cutService.cut_types().subscribe({
      next: (templates) => {
        this.cutTemplates.set(templates);
        if (!this.selectedCutType() && templates.length) {
          this.selectedCutType.set(templates[0].code);
        }
      },
      error: (e) =>
        console.error('Erreur lors du chargement des templates de cuts', e),
    });
  }

  private loadRenderedFiles(): void {
    if (!this.game) return;
    const embedded = this.game._embedded;
    const embeddedTournament = embedded?.['tournament'] as
      | Tournament
      | undefined;
    const tournamentLink = this.game._links?.tournament?.href;
    if (embeddedTournament?._links?.self) {
      this.tournamentService.rendered(embeddedTournament, true).subscribe({
        next: (files) => this.renderedFiles.set(files),
        error: (e) =>
          console.error('Erreur lors du chargement des rendered', e),
      });
      return;
    }
    if (!tournamentLink) return;
    this.tournamentService.get(tournamentLink).subscribe({
      next: (tournament) => {
        if (!tournament) return;
        this.tournamentService.rendered(tournament, true).subscribe({
          next: (files) => this.renderedFiles.set(files),
          error: (e) =>
            console.error('Erreur lors du chargement des rendered', e),
        });
      },
      error: (e) => console.error('Erreur lors du chargement du tournoi', e),
    });
  }

  private slugify(value: string): string {
    return value
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }
}
