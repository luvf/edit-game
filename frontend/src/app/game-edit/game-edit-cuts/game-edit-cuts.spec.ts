import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GameEditCutsComponent } from './game-edit-cuts';

describe('GameEditCutsComponent', () => {
  let component: GameEditCutsComponent;
  let fixture: ComponentFixture<GameEditCutsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [GameEditCutsComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(GameEditCutsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
