import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TournamentViewComponent } from './tournament-view.component';

describe('TournamentsView', () => {
  let component: TournamentViewComponent;
  let fixture: ComponentFixture<TournamentViewComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TournamentViewComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TournamentViewComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
