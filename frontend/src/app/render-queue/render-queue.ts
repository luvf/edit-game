import {
  AfterViewInit,
  Component,
  inject,
  OnInit,
  signal,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSort, MatSortModule } from '@angular/material/sort';
import { RenderQueueItem } from '../core/models/models';
import { RenderQueueService } from '../core/services/misc-hateoas-models.service';
import { forkJoin } from 'rxjs';

@Component({
  selector: 'app-render-queue',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCheckboxModule,
    MatTableModule,
    MatTooltipModule,
    MatSortModule,
  ],
  templateUrl: './render-queue.html',
  styleUrl: './render-queue.css',
})
export class RenderQueueComponent implements OnInit, AfterViewInit {
  items = signal<RenderQueueItem[]>([]);
  dataSource = new MatTableDataSource<RenderQueueItem>([]);
  displayedColumns = [
    'select',
    'game',
    'cut',
    'metadata',
    'status',
    'output',
    'command',
    'started',
    'finished',
    'actions',
  ];
  loading = signal(false);
  error = signal<string | null>(null);
  selection = signal<Set<number>>(new Set());
  @ViewChild(MatSort) sort!: MatSort;
  private renderQueueService = inject(RenderQueueService);

  ngOnInit(): void {
    this.refresh();
  }

  ngAfterViewInit(): void {
    this.dataSource.sort = this.sort;
    this.dataSource.sortingDataAccessor = (item, property) => {
      switch (property) {
        case 'game':
          return (item.game_name ?? item.game ?? '').toString().toLowerCase();
        case 'cut':
          return (item.cut_name ?? item.cut ?? '').toString().toLowerCase();
        case 'metadata':
          return (item.metadata ?? '').toString().toLowerCase();
        case 'status':
          return (item.status ?? '').toString().toLowerCase();
        case 'started':
          return item.started_at ? new Date(item.started_at).getTime() : 0;
        case 'finished':
          return item.finished_at ? new Date(item.finished_at).getTime() : 0;
        default:
          return (
            (item as unknown as Record<string, string | number>)[property] ?? ''
          );
      }
    };
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.renderQueueService.list().subscribe({
      next: (items) => {
        this.items.set(items);
        this.dataSource.data = items;
      },
      error: (e) => {
        this.error.set(e?.message ? String(e.message) : 'Erreur de chargement');
      },
      complete: () => this.loading.set(false),
    });
  }

  isSelected(item: RenderQueueItem): boolean {
    return this.selection().has(item.pk);
  }

  statusClass(item: RenderQueueItem): string {
    const status = (item.status ?? '').toLowerCase();
    switch (status) {
      case 'created':
        return 'status--created';
      case 'waiting':
        return 'status--waiting';
      case 'running':
        return 'status--running';
      case 'done':
        return 'status--done';
      case 'failed':
        return 'status--failed';
      default:
        return '';
    }
  }

  toggleSelection(item: RenderQueueItem, checked: boolean): void {
    const next = new Set(this.selection());
    if (checked) {
      next.add(item.pk);
    } else {
      next.delete(item.pk);
    }
    this.selection.set(next);
  }

  onDelete(item: RenderQueueItem): void {
    this.renderQueueService.delete(item).subscribe({
      next: () => this.refresh(),
      error: (e) => {
        this.error.set(
          e?.message ? String(e.message) : 'Erreur de suppression',
        );
      },
    });
  }

  onRun(item: RenderQueueItem): void {
    this.renderQueueService.run(item).subscribe({
      next: () => this.refresh(),
      error: (e) => {
        this.error.set(e?.message ? String(e.message) : 'Erreur de lancement');
      },
    });
  }

  onReset(item: RenderQueueItem): void {
    this.renderQueueService.reset(item).subscribe({
      next: () => this.refresh(),
      error: (e) => {
        this.error.set(e?.message ? String(e.message) : 'Erreur de reset');
      },
    });
  }

  onBulkDelete(): void {
    const targets = this.items().filter((item) =>
      this.selection().has(item.pk),
    );
    if (!targets.length) return;
    this.loading.set(true);
    forkJoin(
      targets.map((item) => this.renderQueueService.delete(item)),
    ).subscribe({
      next: () => {
        this.selection.set(new Set());
        this.refresh();
      },
      error: (e) => {
        this.loading.set(false);
        this.error.set(
          e?.message ? String(e.message) : 'Erreur de suppression',
        );
      },
    });
  }

  onBulkRun(): void {
    const targets = this.items().filter((item) =>
      this.selection().has(item.pk),
    );
    if (!targets.length) return;
    this.loading.set(true);
    forkJoin(
      targets.map((item) => this.renderQueueService.run(item)),
    ).subscribe({
      next: () => {
        this.selection.set(new Set());
        this.refresh();
      },
      error: (e) => {
        this.loading.set(false);
        this.error.set(e?.message ? String(e.message) : 'Erreur de lancement');
      },
    });
  }

  onBulkReset(): void {
    const targets = this.items().filter((item) =>
      this.selection().has(item.pk),
    );
    if (!targets.length) return;
    this.loading.set(true);
    forkJoin(
      targets.map((item) => this.renderQueueService.reset(item)),
    ).subscribe({
      next: () => {
        this.selection.set(new Set());
        this.refresh();
      },
      error: (e) => {
        this.loading.set(false);
        this.error.set(e?.message ? String(e.message) : 'Erreur de reset');
      },
    });
  }
}
