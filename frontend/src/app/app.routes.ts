import { Routes } from '@angular/router';
import { Nuevo } from './nuevo/nuevo';
import { Reporte } from './reporte/reporte';
import { sinGuardar } from './sop/sin-guardar.guard';
import { SopEditor } from './sop/sop-editor';
import { SopGenerado } from './sop/sop-generado';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'nuevo' },
  { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
  {
    path: 'videos/:id/reporte',
    component: Reporte,
    // Dos columnas (tabla y video): la pantalla usa todo el ancho (app.html).
    data: { ancho: true },
    title: 'Reporte de validación · SOPVID',
  },
  // SOP generado (RF-26): avance del video y luego el editor.
  {
    path: 'videos/:id/sop',
    component: SopGenerado,
    canDeactivate: [sinGuardar],
    title: 'SOP generado · SOPVID',
  },
  // SOP de referencia convertido (RF-04): el mismo editor; `?video=N` para revalidar.
  {
    path: 'sops/:id',
    component: SopEditor,
    canDeactivate: [sinGuardar],
    title: 'Revisar el SOP · SOPVID',
  },
];
