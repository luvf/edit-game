import {Routes} from '@angular/router';
import {TournamentViewComponent} from './tournaments-view/tournament-view.component';
import {TournamentGamesViewComponent} from './tournament-games-view/tournament-games-view';
import {GameMiniatureComponent} from './game-miniature/game-miniature';
import {TournamentEditGamesView} from './tournament-edit-games-view/tournament-edit-games-view';
import {GameEditComponent} from './game-edit/game-edit';

export const routes: Routes = [
  {path: '', redirectTo: 'tournaments', pathMatch: 'full'},
  {path:"tournaments", component : TournamentViewComponent},
  {path: 'tournament/games', component: TournamentGamesViewComponent},
    {path: 'tournament/video-editing', component: TournamentEditGamesView},

  {path: 'game', component: GameMiniatureComponent},
  {path: 'game-edit', component: GameEditComponent},

];
