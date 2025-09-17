import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TeamSelect } from './team-select';

describe('TeamSelect', () => {
  let component: TeamSelect;
  let fixture: ComponentFixture<TeamSelect>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TeamSelect]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TeamSelect);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
