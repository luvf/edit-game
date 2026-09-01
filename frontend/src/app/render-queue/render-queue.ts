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
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSort, MatSortModule } from '@angular/material/sort';
import { RenderQueueItem } from '../core/models/models';
import { RenderQueueService } from '../core/services/misc-hateoas-models.service';
import { forkJoin } from 'rxjs';

/** Colonnes catégorielles filtrables. */
type FilterableColumn = 'game' | 'cut' | 'metadata' | 'status';

@Component({
  selector: 'app-render-queue',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatSelectModule,
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
  filterColumns = this.displayedColumns.map((column) => `${column}-filter`);
  filterableColumns: FilterableColumn[] = ['game', 'cut', 'metadata', 'status'];
  nonFilterableColumns = this.displayedColumns.filter(
    (column) => !(this.filterableColumns as string[]).includes(column),
  );
  loading = signal(false);
  error = signal<string | null>(null);
  selection = signal<Set<number>>(new Set());
  filters = signal<Record<FilterableColumn, string[]>>({
    game: [],
    cut: [],
    metadata: [],
    status: [],
  });
  @ViewChild(MatSort) sort!: MatSort;
  private renderQueueService = inject(RenderQueueService);

  ngOnInit(): void {
    this.dataSource.filterPredicate = (item, filter) => {
      const active = JSON.parse(filter) as Record<FilterableColumn, string[]>;
      return this.filterableColumns.every((column) => {
        const selected = active[column];
        return (
          !selected?.length || selected.includes(this.cellValue(item, column))
        );
      });
    };
    this.applyFilters();
    this.refresh();
  }

  ngAfterViewInit(): void {
    this.dataSource.sort = this.sort;
    this.dataSource.sortingDataAccessor = (item, property) => {
      switch (property) {
        case 'game':
        case 'cut':
        case 'metadata':
        case 'status':
          return this.cellValue(item, property).toLowerCase();
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
        this.pruneFilters();
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

  /** Valeur affichée (et filtrée) d'une colonne catégorielle. */
  cellValue(item: RenderQueueItem, column: FilterableColumn): string {
    switch (column) {
      case 'game':
        return (item.game_name ?? item.game ?? '-').toString();
      case 'cut':
        return (item.cut_name ?? item.cut ?? '-').toString();
      case 'metadata':
        return (item.metadata ?? '').toString();
      case 'status':
        return (item.status ?? '').toString();
    }
  }

  /** Valeurs distinctes disponibles pour une colonne, triées. */
  filterOptions(column: FilterableColumn): string[] {
    const values = new Set(
      this.items().map((item) => this.cellValue(item, column)),
    );
    return [...values].sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true }),
    );
  }

  /** Nombre de lignes après filtrage. */
  filteredCount(): number {
    return this.dataSource.filteredData.length;
  }

  onFilterChange(column: FilterableColumn, values: string[]): void {
    this.filters.set({ ...this.filters(), [column]: values });
    this.applyFilters();
  }

  hasActiveFilters(): boolean {
    return this.filterableColumns.some(
      (column) => this.filters()[column].length > 0,
    );
  }

  clearFilters(): void {
    this.filters.set({ game: [], cut: [], metadata: [], status: [] });
    this.applyFilters();
  }

  /** Pousse les filtres courants dans la MatTableDataSource. */
  private applyFilters(): void {
    this.dataSource.filter = JSON.stringify(this.filters());
  }

  /** Retire les valeurs filtrées qui n'existent plus après un refresh. */
  private pruneFilters(): void {
    const next = { ...this.filters() };
    for (const column of this.filterableColumns) {
      const available = new Set(this.filterOptions(column));
      next[column] = next[column].filter((value) => available.has(value));
    }
    this.filters.set(next);
    this.applyFilters();
  }

  /** Lignes actuellement rendues (tri/filtre/pagination appliqués). */
  pageItems(): RenderQueueItem[] {
    return this.dataSource.connect().value;
  }

  isPageFullySelected(): boolean {
    const page = this.pageItems();
    if (!page.length) return false;
    const selected = this.selection();
    return page.every((item) => selected.has(item.pk));
  }

  isPagePartiallySelected(): boolean {
    const page = this.pageItems();
    if (!page.length) return false;
    const selected = this.selection();
    return (
      page.some((item) => selected.has(item.pk)) && !this.isPageFullySelected()
    );
  }

  togglePageSelection(checked: boolean): void {
    const next = new Set(this.selection());
    for (const item of this.pageItems()) {
      if (checked) {
        next.add(item.pk);
      } else {
        next.delete(item.pk);
      }
    }
    this.selection.set(next);
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
