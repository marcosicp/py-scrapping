import {Injectable} from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';

// import 'rxjs/add/operator/catch';
import { Observable } from 'rxjs';

@Injectable()
export class AppService {

  constructor(private http: HttpClient) {
  }

//   private static _handleError(err: HttpErrorResponse | any) {
//     return Observable.throw(err.message || 'Error: Unable to complete request.');
//   }

  // GET the grouped catalog.
  //
  // The path is relative on purpose: Flask serves this SPA and owns `/api`, so a
  // relative path is same-origin on every host (localhost, Render, Coolify) and
  // needs no CORS or per-build base URL. The previous absolute
  // `http://127.0.0.1:3000/...` could not work anywhere but the developer's own
  // machine: it targets the viewer's loopback, which Chrome blocks under Private
  // Network Access (public origin -> `loopback` address space) with both a CORS
  // log line and `net::ERR_FAILED`.
  getExams(): Observable<any> {
    return this.http.get(`/api/productos/agrupados`);
  }
}