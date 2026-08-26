import { Injectable, signal } from '@angular/core';
import { Cut } from '../../core/models/models';

@Injectable()
export class GameEditCutsStateService {
  readonly rushFrame = signal(0);
  readonly renderedFrame = signal(0);
  readonly activeCut = signal<Cut | null>(null);
}
