import { Component, OnInit, ViewChild } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import { Observable } from 'rxjs';
import { AppService } from 'src/app/service/app.service';
import { TotalValueRenderer } from './cellRender';

@Component({
  selector: 'app-dashboard',
  standalone: false,
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css'],
})
export class DashboardComponent implements OnInit {
  items?: any;
  noRowsTemplate = '¡Agrega tus productos!';
  itemsCarre?: any[] = [];
  itemsDisco?: any[] = [];
  itemsMami?: any[] = [];
  itemsHiper?: any[] = [];
  rowDataClicked1 = {};
  public rowSelection: 'single' | 'multiple' = 'multiple';
  // Each Column Definition results in one Column.
  // -- Master grid: one canonical row per product, one price column per chain
  public columnDefs: ColDef[] = [
    {
      headerName: '',
      flex: 0,
      sortable: true,
      filter: true,
      cellStyle: { textAlign: 'center' },
      cellRenderer: TotalValueRenderer,
      cellRendererParams: {
        clicked: (data: any) => {
          data.selected = !data.selected;
          this.addItemToList(data);
        },
      },
    },
    {
      field: 'name',
      headerName: 'Producto',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 2,
    },
    {
      field: 'unidad',
      headerName: 'Presentación',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 1,
    },
    {
      field: 'brand',
      headerName: 'Marca',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      flex: 1,
    },
    {
      field: 'offers.carre.price',
      headerName: 'Carrefour',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.disco.price',
      headerName: 'Disco',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.mami.price',
      headerName: 'SuperMami',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
    {
      field: 'offers.hiper.price',
      headerName: 'La Anónima',
      sortable: true,
      filter: true,
      suppressSizeToFit: true,
      cellRenderer: (param: any) => {
        return param.value == null ? '' : '$' + param.value;
      },
      flex: 1,
    },
  ];

  public columnDefsGeneric: ColDef[] = [
    {
      field: 'name',
      suppressSizeToFit: true,
      flex: 1,
      headerName: 'Nombre',
      cellStyle: { fontSize: '11px' },
    },
    {
      field: 'price',
      headerName: 'Precio',
      cellStyle: { fontSize: '11px' },
      cellRenderer: (param: any) => {
        return '$' + param.value;
      },
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
    this.gridApi.setGridOption('quickFilterText',
      (document.getElementById('filter-text-box') as HTMLInputElement).value
    );
  }

  totalRow(api: any, listaSuper: any) {
    var result = { name: 'Total', price: 0 };
    const calcTotalCols = ['price'];
    calcTotalCols.forEach((params) => {
      (listaSuper ?? []).forEach((line: { [x: string]: any }) => {
        result.price = Number(result.price) + Number(line[params]);
      });
    });

    // -- R3-001: a grid that has not fired gridReady yet (or was never
    // rendered) must not abort the selection path; the array still updates.
    if (api && typeof api.setPinnedBottomRowData === 'function') {
      api.setPinnedBottomRowData([result]);
    }
  }

  // -- D-1: selecting a canonical row adds EVERY present offer to its own
  // chain list ({name, price} of that offer); deselecting removes them.
  addItemToList(data: any) {
    const offers = data.offers || {};

    // -- Carrefour
    if (offers.carre) {
      this.itemsCarre = this.addRemoveOffer(offers.carre, data.selected, this.itemsCarre);
      this.totalRow(this.gridApi4, this.itemsCarre);
    }
    // -- Disco
    if (offers.disco) {
      this.itemsDisco = this.addRemoveOffer(offers.disco, data.selected, this.itemsDisco);
      this.totalRow(this.gridApi3, this.itemsDisco);
    }
    // -- SuperMami
    if (offers.mami) {
      this.itemsMami = this.addRemoveOffer(offers.mami, data.selected, this.itemsMami);
      this.totalRow(this.gridApi1, this.itemsMami);
    }
    // -- La Anónima
    if (offers.hiper) {
      this.itemsHiper = this.addRemoveOffer(offers.hiper, data.selected, this.itemsHiper);
      this.totalRow(this.gridApi2, this.itemsHiper);
    }
  }
  addRemoveOffer(offer: any, selected: any, items: any[] | undefined): any[] {
    // -- R3-001: never dereference an undefined list; a chain list that was
    // never initialized starts empty instead of throwing mid-selection.
    const list = items ?? [];
    if (selected) {
      // Se agrega solo si el nombre no está ya en la lista
      return list.some((item) => item.name === offer.name)
        ? list
        : list.concat([{ name: offer.name, price: offer.price }]);
    }
    // Se elimina por nombre
    return list.filter((item) => item.name !== offer.name);
  }
}
