import {
  Component,
  computed,
  ElementRef,
  inject,
  Input,
  OnChanges,
  OnInit,
  signal,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {MatTabsModule} from '@angular/material/tabs';
import {MatButtonModule} from '@angular/material/button';
import {MatCardModule} from '@angular/material/card';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatSelectModule} from '@angular/material/select';
import {CutsService, GamesService} from '../../core/services/misc-hateoas-models.service';
import {TournamentService} from '../../core/services/tournament.service';
import {Cut, Game, Tournament} from '../../core/models/models';
import {CutDetailComponent} from '../cut-detail/cut-detail';
import {VideoPlayer} from '../video-player/video-player';

type CutTemplate = {
  code: string;
  label: string;
};


@Component({
  selector: 'app-game-edit-cuts',
  standalone: true,
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
    VideoPlayer,

  ],
  templateUrl: './game-edit-cuts.html',
  styleUrl: './game-edit-cuts.css',
})
export class GameEditCutsComponent implements OnChanges,OnInit {
  @Input() game?: Game | null = null;


  rushFrame = signal(0);
  renderedFrame = signal(0);


  cuts = signal<Cut[]>([]);
  cutTemplates = signal<CutTemplate[]>([]);
  newCutName = signal('');
  selectedCutType = signal<string | null>(null);
  loadedFile = signal<File | null>(null);
  renderedFiles = signal<string[]>([]);
  selectedRendered = signal<string | null>(null);

  selectedCutTabIndex = signal(0);

  activeCut = computed(() => {
    return this.cuts()[this.selectedCutTabIndex()] ?? null;
  });

  @ViewChild('proxyVideo') proxyVideo?: ElementRef<HTMLVideoElement>;
  protected readonly length = length;

  private gameService = inject(GamesService);
  private cutService = inject(CutsService);
  private tournamentService = inject(TournamentService);



  ngOnInit(): void {

    this.loadCutTemplates();
    if (!this.game) return;
    this.loadCuts();
    this.loadRenderedFiles();
  }


  ngOnChanges(changes: SimpleChanges): void {
    if (changes['cuts'] || changes['game']) {
      this.loadCuts();
      this.loadRenderedFiles();
    }

  }


  onGenerateCut(): void {
    if (!this.game) return;
    const selectedType = this.selectedCutType();
    const template = this.cutTemplates().find((item) => item.code === selectedType);
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
                this.cuts().map((item) => (item.pk === updated.pk ? updated : item))
              );
              this.loadedFile.set(null);
            },
            error: (e) => console.error("Erreur lors de l'upload du json OTIO", e),
          });
        } else if (template.code === 'VID') {
          const filename = this.selectedRendered();
          if (!filename) return;
          this.cutService.gen_from_rendered(cut, {filename}).subscribe({
            next: (updated) => {
              this.cuts.set(
                this.cuts().map((item) => (item.pk === updated.pk ? updated : item))
              );
              this.selectedRendered.set(null);
            },
            error: (e) => console.error("Erreur lors du cut depuis rendered", e),
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
    this.cutService.render_cut(cut, {to_queue: false}).subscribe({
      next: () => {},
      error: (e) => console.error('Erreur lors du render du cut', e),
    });
  }

  onSelectedCutTabChange(index: number): void {
  this.selectedCutTabIndex.set(index);
  }
  private loadCuts(): void {
    if (!this.game) return;
  this.gameService.cuts(this.game).subscribe({
    next: (cuts) => {
      this.cuts.set(cuts);

      if (this.selectedCutTabIndex() >= cuts.length) {
        this.selectedCutTabIndex.set(Math.max(0, cuts.length - 1));
      }
    },
    error: (e) => console.error('Erreur lors du chargement des cuts', e),
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
      error: (e) => console.error('Erreur lors du chargement des templates de cuts', e),
    });
  }

  private loadRenderedFiles(): void {
    if (!this.game) return;
    const embedded = this.game._embedded;
    const embeddedTournament = embedded?.['tournament'] as Tournament | undefined;
    const tournamentLink = this.game._links?.tournament?.href;
    if (embeddedTournament?._links?.self) {
      this.tournamentService.rendered(embeddedTournament, true).subscribe({
        next: (files) => this.renderedFiles.set(files),
        error: (e) => console.error('Erreur lors du chargement des rendered', e),
      });
      return;
    }
    if (!tournamentLink) return;
    this.tournamentService.get(tournamentLink).subscribe({
      next: (tournament) => {
        if (!tournament) return;
        this.tournamentService.rendered(tournament, true).subscribe({
          next: (files) => this.renderedFiles.set(files),
          error: (e) => console.error('Erreur lors du chargement des rendered', e),
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
