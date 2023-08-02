import { Component, OnInit, ViewChild } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import { Observable } from 'rxjs';
import { AppService } from 'src/app/service/app.service';
import { TotalValueRenderer } from './cellRender';

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css'],
})
export class DashboardComponent implements OnInit {
  items?: any;
  noRowsTemplate = "¡Agrega tus productos!";
  itemsCarre?: any[] = [];
  itemsDisco?: any[] = [];
  itemsMami?: any[] = [];
  itemsHiper?: any[] = [];
  rowDataClicked1 = {};
  public rowSelection: 'single' | 'multiple' = 'multiple';
  // Each Column Definition results in one Column.
  public columnDefs: ColDef[] = [
    {
      headerName: '',
      flex: 0,
      sortable: true,
      filter: true,
      cellStyle: {textAlign: 'center'},
      cellRenderer: TotalValueRenderer,
      cellRendererParams: {
        clicked: (data: any) => {
          data.selected = !data.selected;
          this.addItemToList(data);
        },
      },
    },
    {
      field: 'name',headerName:'Nombre',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 2,
    },
    {
      field: 'price',
      headerName:'Precio',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) =>{ return '$' + param.value},
      flex: 1,
    },
    {
      field: 'supermercado',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 1,
    },
  ];

  public columnDefsGeneric: ColDef[] = [
    {
      field: 'name',
      suppressSizeToFit: true,
      flex: 1,
      headerName:'Nombre',
      cellStyle: {fontSize: '11px'}
    },
    {
      field: 'price',
      headerName:'Precio',
      cellStyle: {fontSize: '11px'},
      cellRenderer: (param: any) =>{ return '$' + param.value},
      suppressSizeToFit: true,
      flex: 1,
    },
  ];

  // DefaultColDef sets props common to all Columns
  public defaultColDef: ColDef = {
    sortable: true,
    filter: true,
  };

  // Data that gets displayed in the grid
  public rowData$!: Observable<any>;
  private gridApi!: GridApi;

  private gridApi1!: GridApi;
  private gridApi2!: GridApi;
  private gridApi3!: GridApi;
  private gridApi4!: GridApi;

  constructor(private http: AppService) {}

  @ViewChild(AgGridAngular) agGrid!: AgGridAngular;

  @ViewChild(AgGridAngular) agGrid1!: AgGridAngular;
  @ViewChild(AgGridAngular) agGrid2!: AgGridAngular;
  @ViewChild(AgGridAngular) agGrid3!: AgGridAngular;
  @ViewChild(AgGridAngular) agGrid4!: AgGridAngular;

  ngOnInit() {
    this.http.getExams().subscribe((a) => {
      this.items = a;
    });
  }

  // Example load data from server
  onGridReady(params: GridReadyEvent) {
    this.gridApi = params.api;
  }

  onGridReady1(params: GridReadyEvent) {
    this.gridApi1 = params.api;
  }

  onGridReady2(params: GridReadyEvent) {
    this.gridApi2 = params.api;
  }

  onGridReady3(params: GridReadyEvent) {
    this.gridApi3 = params.api;
  }

  onGridReady4(params: GridReadyEvent) {
    this.gridApi4 = params.api;
  }

  onFilterTextBoxChanged() {
    this.gridApi.setQuickFilter(
      (document.getElementById('filter-text-box') as HTMLInputElement).value
    );
  }

  totalRow(api: any, listaSuper: any) {
    var result = { name: 'Total',price: 0 };
    const calcTotalCols = ['price'];
    calcTotalCols.forEach((params) => {
      listaSuper.forEach((line: { [x: string]: any }) => {
        result.price = Number(result.price) + Number(line[params]);
      });
    });


    api.setPinnedBottomRowData([result]);
  }

  addItemToList(data: any) {
    switch (data.supermercado) {
      case 'SuperMami':
        this.itemsMami = this.addRemoveItemByName(data, this.itemsMami!);
        // new agGrid.Grid(gridDiv, gridOptions);
        this.totalRow(this.gridApi1, this.itemsMami);
        break;
      case 'Disco':
        this.itemsDisco = this.addRemoveItemByName(data, this.itemsDisco!);
        this.totalRow(this.gridApi3, this.itemsDisco);
        break;

      case 'Carrefour':
        this.itemsCarre = this.addRemoveItemByName(data, this.itemsCarre!);
        this.totalRow(this.gridApi4, this.itemsCarre);
        break;

      case 'Hiperlibertad':
        this.itemsHiper = this.addRemoveItemByName(data, this.itemsHiper!);
        this.totalRow(this.gridApi2, this.itemsHiper);
        break;
      default:
        break;
    }
  }
  addRemoveItemByName(data: any, items: any[]): any[] {
    var index = items?.findIndex((item) => item.name === data.name);

    if (index === -1) {
      // El elemento no se encontró, entonces lo agregamos
      items = items?.concat([data]);
    } else {
      // El elemento se encontró, entonces lo eliminamos
      items = items?.filter((item, i) => i !== index);
    }

    return items;
  }
}
