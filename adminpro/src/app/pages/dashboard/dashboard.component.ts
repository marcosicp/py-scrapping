import { Component, OnInit, ViewChild } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import { Observable } from 'rxjs';
import { AppService } from 'src/app/service/app.service';


@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.component.html',

  styles: [],
})
export class DashboardComponent implements OnInit {
  items?: any;
  // Each Column Definition results in one Column.
  public columnDefs: ColDef[] = [
    { field: 'name', sortable: true, filter: true, suppressSizeToFit: true,flex:1, },
    { field: 'price', sortable: true, filter: true, suppressSizeToFit: true ,flex:1,},
    { field: 'supermercado', sortable: true, filter: true, suppressSizeToFit: true,flex:1, },
  ];
  // DefaultColDef sets props common to all Columns
  public defaultColDef: ColDef = {
    sortable: true,
    filter: true,
  };

  // Data that gets displayed in the grid
  public rowData$!: Observable<any>;
  private gridApi!: GridApi;
  constructor(private http: AppService) {}

  @ViewChild(AgGridAngular) agGrid!: AgGridAngular;

  ngOnInit() {
    this.http.getExams().subscribe((a) => {
      // debugger;
      this.items = a;
    });
  }

  // Example load data from server
  onGridReady(params: GridReadyEvent) {
    this.gridApi = params.api;
  }

  onFilterTextBoxChanged() {
    this.gridApi.setQuickFilter(
      (document.getElementById('filter-text-box') as HTMLInputElement).value
    );
  }
}
