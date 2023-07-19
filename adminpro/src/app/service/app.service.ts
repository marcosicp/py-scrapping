import {Injectable} from '@angular/core';
import {HttpClient, HttpErrorResponse} from '@angular/common/http';

// import 'rxjs/add/operator/catch';
import { Observable } from 'rxjs';

@Injectable()
export class AppService {

  constructor(private http: HttpClient) {
  }

//   private static _handleError(err: HttpErrorResponse | any) {
//     return Observable.throw(err.message || 'Error: Unable to complete request.');
//   }

  // GET list of public, future events
  getExams(): Observable<any> {
    // debugger;
    return this.http
      .get(`https://p-cd22.onrender.com/supermercados`)
      
  }
}