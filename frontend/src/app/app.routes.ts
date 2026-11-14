import { Routes } from '@angular/router';
import { Biblioteca } from './biblioteca/biblioteca';
import { Nuevo } from './nuevo/nuevo';
import { Procesando } from './procesando/procesando';
import { Reporte } from './reporte/reporte';
import { sinGuardar } from './sop/sin-guardar.guard';
import { SopEditor } from './sop/sop-editor';
import { SopGenerado } from './sop/sop-generado';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'nuevo' },
  { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
  // Biblioteca de SOP (RF-05): en escritorio, filas de tabla a todo el ancho.
  {
    path: 'sops',
    component: Biblioteca,
    data: { ancho: true },
    title: 'Biblioteca de SOP · SOPVID',
  },
  // Avance en vivo por etapa (RF-08): /nuevo llega aquí al enviar; al terminar sigue al resultado.
  {
    path: 'videos/:id/procesando',
    component: Procesando,
    title: 'Procesando · SOPVID',
  },
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
