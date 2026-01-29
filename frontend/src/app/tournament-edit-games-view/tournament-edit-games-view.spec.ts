import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TournamentEditGamesView } from './tournament-edit-games-view';

describe('TournamentEditGamesView', () => {
  let component: TournamentEditGamesView;
  let fixture: ComponentFixture<TournamentEditGamesView>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TournamentEditGamesView]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TournamentEditGamesView);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
