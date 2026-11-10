// Proxy de `ng serve`: reenvía /api a la API sin el prefijo (la API no tiene CORS).
// El destino sale de API_URL; sin ella, la API en el host (ng serve corriendo en Windows).
//   http://api:8000                   Angular y la API en Docker (servicio "web" de compose)
//   http://host.docker.internal:8000  Angular en Docker y la API en el host (make up-gpu)
module.exports = {
  "/api": {
    target: process.env.API_URL || "http://localhost:8000",
    secure: false,
    pathRewrite: { "^/api": "" },
  },
};
