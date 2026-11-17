import { Routes } from '@angular/router';
import { Acceso } from './acceso/acceso';
import { requiereVista } from './acceso/acceso.guard';
import { Biblioteca } from './biblioteca/biblioteca';
import { Inicio } from './inicio/inicio';
import { Nuevo } from './nuevo/nuevo';
import { Procesando } from './procesando/procesando';
import { Reporte } from './reporte/reporte';
import { sinGuardar } from './sop/sin-guardar.guard';
import { SopEditor } from './sop/sop-editor';
import { SopGenerado } from './sop/sop-generado';
import { Ver } from './ver/ver';

export const routes: Routes = [
  // Clave de acceso de una vista (§11, ADR-027): `?vista=carga|busqueda&volver=<url>`. Sin menú.
  {
    path: 'acceso',
    component: Acceso,
    data: { consulta: true },
    title: 'Clave de acceso · SOPVID',
  },
  // Búsqueda (pantalla 7, RF-36): vista de consulta que pide la clave de búsqueda. Muestra la
  // barra principal (`menu`) para navegar a las demás pantallas; los enlaces a la vista de carga
  // piden su propia clave.
  {
    path: 'buscar',
    loadComponent: () => import('./buscar/buscar').then((m) => m.Buscar),
    canActivate: [requiereVista],
    data: { ancho: true, consulta: true, menu: true, vista: 'busqueda' },
    title: 'Búsqueda · SOPVID',
  },
  // Destino de los QR del PDF (§11): el video en ese segundo, sin clave si el enlace trae su
  // token (`k`); con la sesión de carga, además el enlace al reporte o al SOP. Sin menú.
  {
    path: 'v/:id',
    component: Ver,
    data: { ancho: true, consulta: true },
    title: 'Video · SOPVID',
  },
  // Vista de carga (§11): todas sus pantallas piden la clave de carga (padre sin componente; los
  // hijos heredan `data.vista`).
  {
    path: '',
    canActivateChild: [requiereVista],
    data: { vista: 'carga' },
    children: [
      // Inicio (`/`): una tarjeta por pantalla.
      { path: '', pathMatch: 'full', component: Inicio, title: 'Inicio · SOPVID' },
      { path: 'nuevo', component: Nuevo, title: 'Nuevo análisis · SOPVID' },
      // Biblioteca de SOP (RF-05): en escritorio, filas de tabla a todo el ancho.
      {
        path: 'sops',
        component: Biblioteca,
        data: { ancho: true },
        title: 'Biblioteca de SOP · SOPVID',
      },
      // Lista de videos (pantalla 6, #29): cada fila lleva al avance, al reporte o al SOP
      // generado. Se carga al entrar (loadComponent): no suma al bundle inicial.
      {
        path: 'videos',
        loadComponent: () => import('./videos/videos').then((m) => m.Videos),
        data: { ancho: true },
        title: 'Videos · SOPVID',
      },
      // Avance en vivo por etapa (RF-08): /nuevo llega aquí al enviar; al terminar sigue al
      // resultado.
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
    ],
  },
  // Una URL que no existe cae en Inicio (y, si falta, en la clave de carga).
  { path: '**', redirectTo: '' },
];
