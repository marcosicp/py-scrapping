import { Component } from '@angular/core';

@Component({
  selector: 'app-no-page-found',
  standalone: false,
  templateUrl: './no-page-found.component.html',
  styleUrls: ['./no-page-found.component.css']
})
export class NoPageFoundComponent {

  public year = new Date().getFullYear()

}
