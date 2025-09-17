import { Routes } from '@angular/router';
import { TournamentViewComponent } from './tournaments-view/tournament-view.component';
import {TournamentGamesViewComponent} from './tournament-games-view/tournament-games-view';
import {GameViewComponent} from './game-view/game-view';

export const routes: Routes = [
  {path:"tournaments", component : TournamentViewComponent},
  {path: 'tournament/games', component: TournamentGamesViewComponent},
  {path: 'game', component: GameViewComponent},

];
