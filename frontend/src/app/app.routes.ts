import { Routes } from '@angular/router';
import { Biblioteca } from './biblioteca/biblioteca';
import { Nuevo } from './nuevo/nuevo';
import { Procesando } from './procesando/procesando';
import { Reporte } from './reporte/reporte';
import { sinGuardar } from './sop/sin-guardar.guard';
import { SopEditor } from './sop/sop-editor';
import { SopGenerado } from './sop/sop-generado';
import { Ver } from './ver/ver';

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
  // Lista de videos (pantalla 6, #29): cada fila lleva al avance, al reporte o al SOP generado.
  // Las dos pantallas de S6 se cargan al entrar (loadComponent): no suman al bundle inicial.
  {
    path: 'videos',
    loadComponent: () => import('./videos/videos').then((m) => m.Videos),
    data: { ancho: true },
    title: 'Videos · SOPVID',
  },
  // Búsqueda (pantalla 7, RF-36): vista de consulta, sin el menú de la vista de carga (app.html).
  {
    path: 'buscar',
    loadComponent: () => import('./buscar/buscar').then((m) => m.Buscar),
    data: { ancho: true, consulta: true },
    title: 'Búsqueda · SOPVID',
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
  // Destino de los QR del PDF (§11): lleva al reporte o al SOP generado con `?t=`.
  { path: 'v/:id', component: Ver, title: 'Abriendo el video · SOPVID' },
];
