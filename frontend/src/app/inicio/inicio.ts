import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

interface Tarjeta {
  ruta: string;
  titulo: string;
  descripcion: string;
  accion: string;
}

/**
 * Pantalla de inicio (`/`): un punto de partida con una tarjeta por pantalla de la aplicación.
 * Es estática (sin llamadas a la API) y vive en la vista de carga, así que pide su clave.
 */
@Component({
  selector: 'app-inicio',
  imports: [RouterLink],
  templateUrl: './inicio.html',
  styleUrl: './inicio.scss',
})
export class Inicio {
  protected readonly tarjetas: readonly Tarjeta[] = [
    {
      ruta: '/nuevo',
      titulo: 'Nuevo análisis',
      descripcion: 'Sube un video para validarlo contra un SOP o para generar el SOP desde él.',
      accion: 'Subir un video',
    },
    {
      ruta: '/sops',
      titulo: 'Biblioteca de SOP',
      descripcion: 'Los SOP de referencia: súbelos, revísalos, edítalos o bórralos.',
      accion: 'Abrir la biblioteca',
    },
    {
      ruta: '/videos',
      titulo: 'Videos',
      descripcion: 'Los videos analizados con su estado, su reporte o su SOP, y la publicación.',
      accion: 'Ver los videos',
    },
    {
      ruta: '/buscar',
      titulo: 'Búsqueda',
      descripcion: 'Encuentra una palabra o frase en los videos publicados y salta a ese segundo.',
      accion: 'Buscar en los videos',
    },
  ];
}
