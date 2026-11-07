import { Routes } from '@angular/router';
import { Nuevo } from './nuevo/nuevo';
import { Reporte } from './reporte/reporte';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'nuevo' },
  { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
  {
    path: 'videos/:id/reporte',
    component: Reporte,
    title: 'Reporte de validación · SOPVID',
  },
];
