import { CUSTOM_ELEMENTS_SCHEMA, NgModule, provideZoneChangeDetection } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppComponent } from './app.component';
import { RegisterComponent } from './auth/register/register.component';
import { LoginComponent } from './auth/login/login.component';
import { NoPageFoundComponent } from './pages/no-page-found/no-page-found.component';
import { DashboardComponent } from './pages/dashboard/dashboard.component';
import { BreadcrumbsComponent } from './shared/breadcrumbs/breadcrumbs.component';
import { SidebarComponent } from './shared/sidebar/sidebar.component';
import { HeaderComponent } from './shared/header/header.component';
import { ProgressComponent } from './pages/progress/progress.component';
import { Grafica1Component } from './pages/grafica1/grafica1.component';
import { AppRoutingModule } from './app-routing.module';
import { PagesComponent } from './pages/pages.component';
import { AppService } from './service/app.service';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
// import { AppRoutingComponent } from './app-routing/app-routing.component';
import { MatGridListModule } from '@angular/material/grid-list';
import { AgGridModule } from 'ag-grid-angular';
import { HashLocationStrategy, LocationStrategy } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { TotalValueRenderer } from './pages/dashboard/cellRender';


@NgModule({ declarations: [
        AppComponent,
        RegisterComponent,
        LoginComponent,
        NoPageFoundComponent,
        DashboardComponent,
        BreadcrumbsComponent,
        SidebarComponent,
        HeaderComponent,
        ProgressComponent,
        Grafica1Component,
        PagesComponent,
        TotalValueRenderer
        // AppRoutingComponent
    ],
    schemas: [CUSTOM_ELEMENTS_SCHEMA],
    bootstrap: [AppComponent], imports: [BrowserModule,
        AppRoutingModule,
        NoopAnimationsModule,
        MatGridListModule,
        MatIconModule,
        AgGridModule], providers: [AppService,
        // Angular 21 does not turn on zone-driven change detection on its own
        // for a platformBrowserDynamic bootstrap: without this provider an
        // async callback (an HttpClient response, for instance) updates the
        // component and never schedules a render.
        provideZoneChangeDetection({ eventCoalescing: true }),
        { provide: LocationStrategy, useClass: HashLocationStrategy },
        provideHttpClient(withInterceptorsFromDi()),] })
export class AppModule {}
