
# AdminPro — Frontend Angular para LaListita

Frontend Angular 19 del sistema de comparación de precios de supermercados argentinos. Se integra con el backend Flask que lo sirve como archivos estáticos.

## Tech Stack

- **Angular 19.2** con NgModules (`standalone: false` explícito en cada componente)
- **Angular Material 19** (tema `pink-bluegrey`)
- **ag-grid-angular 32** para tablas de productos
- **TypeScript 5.8**, Zone.js 0.15
- **Builder:** `@angular-devkit/build-angular:application` (esbuild)
- **Routing:** `HashLocationStrategy` (URLs con `#`)

## Estructura del proyecto

```
src/app/
├── app.module.ts              # NgModule principal (NO standalone)
├── app-routing.module.ts      # Rutas de la app
├── app.component.ts           # Componente raíz (<router-outlet>)
├── service/
│   └── app.service.ts         # HttpClient → GET /supermercados
├── pages/
│   ├── pages.component.ts     # Layout con header + breadcrumbs + <router-outlet>
│   ├── dashboard/
│   │   ├── dashboard.component.ts   # Componente principal: 5 ag-grids, búsqueda
│   │   ├── dashboard.component.html # Template con grids por supermercado
│   │   └── cellRender.ts           # Custom cell renderer (checkbox) para ag-grid
│   ├── progress/              # Placeholder (vacío)
│   ├── grafica1/              # Placeholder (vacío)
│   └── no-page-found/        # Página 404
├── auth/
│   ├── login/                 # Placeholder login
│   └── register/              # Placeholder registro
└── shared/
    ├── header/                # Header de la app
    ├── sidebar/               # Sidebar (comentado en template)
    └── breadcrumbs/           # Breadcrumbs
```

## Rutas

| Ruta | Componente | Descripción |
|---|---|---|
| `/` | Redirect → `/dashboard` | |
| `/dashboard` | `PagesComponent` → `DashboardComponent` | Grilla principal de productos |
| `/dashboard/progress` | `ProgressComponent` | Placeholder |
| `/dashboard/grafica1` | `Grafica1Component` | Placeholder |
| `/login` | `LoginComponent` | Placeholder |
| `/register` | `RegisterComponent` | Placeholder |
| `/**` | `NoPageFoundComponent` | 404 |

## Módulos y providers registrados en AppModule

- `BrowserModule`, `AppRoutingModule`, `NoopAnimationsModule`
- `MatGridListModule`, `MatIconModule` (Angular Material)
- `AgGridModule` (ag-grid)
- `provideHttpClient(withInterceptorsFromDi())` — reemplazó a `HttpClientModule`
- `AppService` — servicio HTTP para obtener productos
- `HashLocationStrategy` — URLs con `#` para compatibilidad con Flask static serving

## Build y despliegue

```bash
npm install
ng build                          # Build de producción (default)
ng build --configuration development  # Build de desarrollo
```

**Output:** Se genera en `../static/` (raíz del proyecto Flask), configurado en `angular.json` con `outputPath.base: "../static"` y `outputPath.browser: ""`.

Flask sirve estos archivos estáticos directamente.

## Datos importantes para desarrollo

- **API endpoint:** `AppService` hace `GET http://127.0.0.1:3000/supermercados` (hardcoded en `app.service.ts`)
- **ag-grid API:** Usa `gridApi.setGridOption('quickFilterText', value)` para búsqueda (NO `setQuickFilter` que fue deprecado)
- **Todos los componentes tienen `standalone: false`** porque la app usa NgModules. Angular 19 defaultea a `standalone: true`, por lo que es obligatorio el flag explícito
- **Dashboard:** Muestra 5 ag-grids (1 principal + 4 por supermercado: Carrefour, Disco, HiperLibertad, SuperMami). Los usuarios seleccionan productos con checkbox para comparar precios
- **Estilos:** Algunos CSS warnings al build por hojas de estilo referenciadas en templates HTML que vienen del backend (`/assets/plugins/bootstrap/css/bootstrap.min.css`, `/assets/css/style.css`, `/assets/css/colors/default-dark.css`) — son inyectados por Flask templates, no por Angular
