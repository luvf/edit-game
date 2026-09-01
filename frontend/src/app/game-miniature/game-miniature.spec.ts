import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GameMiniatureComponent } from './game-miniature';

describe('GameMiniatureComponent', () => {
  let component: GameMiniatureComponent;
  let fixture: ComponentFixture<GameMiniatureComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GameMiniatureComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(GameMiniatureComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
