import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CutTimelineComponent } from './cut-timeline';
import { CutCurves } from '../../core/models/models';

/** Des courbes de 5 pas, 1 s chacun, comme le serveur les renvoie. */
function curves(overrides: Partial<CutCurves> = {}): CutCurves {
  return {
    hop: 1,
    duration: 5,
    points: 5,
    steps: 5,
    fps: 60,
    in: [0, 0.25, 1, 0.25, 0],
    out: [0, 0, 0, 0, 1],
    inside: [0.1, 0.9, 0.9, 0.9, 0.1],
    decode: { threshold: { in: 0.5, out: 0.7 } },
    ...overrides,
  };
}

describe('CutTimelineComponent', () => {
  let fixture: ComponentFixture<CutTimelineComponent>;
  let component: CutTimelineComponent;

  beforeEach(async () => {
    // L'application tourne sans zone.js : sans ce fournisseur, TestBed
    // reclame Zone.js et rien ne demarre.
    await TestBed.configureTestingModule({
      imports: [CutTimelineComponent],
      providers: [provideZonelessChangeDetection()],
    }).compileComponents();

    fixture = TestBed.createComponent(CutTimelineComponent);
    component = fixture.componentInstance;
  });

  it('ne dessine rien sans courbes', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.detectChanges();

    expect(component.curveShapes().length).toBe(0);
    expect(fixture.nativeElement.querySelector('.curves')).toBeNull();
  });

  it('dessine les trois canaux quand le cut en porte', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();

    expect(component.curveShapes().map((c) => c.channel)).toEqual([
      'inside',
      'out',
      'in',
    ]);
    expect(fixture.nativeElement.querySelectorAll('.curve').length).toBe(3);
  });

  it('etale les courbes sur la duree reelle, pas sur toute la largeur', () => {
    // 5 s a 60 fps = 300 frames : les courbes couvrent exactement la barre.
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();
    expect(component.curveSpan()).toBeCloseTo(100, 3);

    // Un rush deux fois plus long : les courbes s'arretent au milieu, ce qui
    // doit se voir plutot que d'etre etire en silence.
    fixture.componentRef.setInput('durationFrames', 600);
    fixture.detectChanges();
    expect(component.curveSpan()).toBeCloseTo(50, 3);
  });

  it('projette un pic en haut du repere', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();

    const shape = component.curveShapes().find((c) => c.channel === 'in')!;
    const [x, y] = shape.points.split(' ')[2].split(',').map(Number);

    // Le pic vaut 1 au 3e des 5 pas : au milieu en x, au sommet en y.
    expect(x).toBeCloseTo(50, 2);
    expect(y).toBeCloseTo(0, 2);
  });

  it('place le seuil a sa hauteur et laisse inside sans seuil', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();

    const shapes = component.curveShapes();
    expect(shapes.find((c) => c.channel === 'in')!.threshold).toBe(0.5);
    expect(shapes.find((c) => c.channel === 'inside')!.threshold).toBeNull();
    expect(component.thresholdY(0.5)).toBe(50);
  });

  it("dessine l'apercu dans sa propre voie, sans toucher au montage", () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('points', [{ in: 0, out: 60 }]);
    fixture.componentRef.setInput('previewPoints', [
      { in: 30, out: 90 },
      { in: 150, out: 210 },
    ]);
    fixture.detectChanges();

    expect(component.segments().length).toBe(1);
    expect(component.previewSegments().length).toBe(2);
    expect(component.previewSegments()[0].left).toBeCloseTo(10, 3);
    expect(
      fixture.nativeElement.querySelectorAll('.preview-segment').length,
    ).toBe(2);
    // Le montage enregistre reste seul dans la barre principale.
    expect(
      fixture.nativeElement.querySelectorAll('.track .segment').length,
    ).toBe(1);
  });

  it("ne montre aucune voie d'apercu par defaut", () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('points', [{ in: 0, out: 60 }]);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.preview-track')).toBeNull();
  });

  it('pose les reperes de revue et emmene le lecteur au clic', () => {
    const seeked: number[] = [];
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('reviewMarkers', [
      {
        frame: 150,
        kind: 'in_incertain',
        detail: 'score 0.52',
        source: 'review',
      },
      {
        frame: 240,
        kind: 'out_orphelin',
        detail: 'out sans in ouvert',
        source: 'rejected',
      },
    ]);
    fixture.detectChanges();
    component.seek.subscribe((frame) => seeked.push(frame));

    const ticks: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.review-tick'),
    );
    expect(ticks.length).toBe(2);
    expect(component.reviewTicks()[0].left).toBeCloseTo(50, 3);
    expect(ticks[1].classList).toContain('is-rejected');

    ticks[1].dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    // La frame exacte du repere, pas la position du pointeur.
    expect(seeked).toEqual([240]);
  });

  it('ignore un repere tombe hors du rush', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('reviewMarkers', [
      {
        frame: 900,
        kind: 'pause_longue',
        detail: 'hors champ',
        source: 'review',
      },
    ]);
    fixture.detectChanges();

    expect(component.reviewTicks().length).toBe(0);
  });

  it('lit les trois probabilites sous le curseur', () => {
    fixture.componentRef.setInput('durationFrames', 300);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();

    component.hoverFrame.set(150);
    expect(component.hoverValues()).toBe('in 1.00 · out 0.00 · dans 0.90');
  });

  it('ne lit rien au-dela de la fin des courbes', () => {
    fixture.componentRef.setInput('durationFrames', 600);
    fixture.componentRef.setInput('curves', curves());
    fixture.detectChanges();

    component.hoverFrame.set(590);
    expect(component.hoverValues()).toBe('');
  });
});
