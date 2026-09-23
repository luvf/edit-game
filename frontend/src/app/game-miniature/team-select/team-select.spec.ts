import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TeamSelectComponent } from './team-select';

describe('TeamSelectComponent', () => {
  let component: TeamSelectComponent;
  let fixture: ComponentFixture<TeamSelectComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TeamSelectComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(TeamSelectComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
